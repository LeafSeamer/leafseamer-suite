package main

import (
	"archive/tar"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

const tarBlock = 512
const restoredDirectory = "restored.partial"

var (
	errTar              = errors.New("backup_archive_tar")
	errArchiveIntegrity = errors.New("backup_archive_integrity")
	errArchiveOutput    = errors.New("backup_archive_output")
)

type archiveReceipt struct {
	State          string `json:"state"`
	ArchiveBytes   int64  `json:"archive_bytes"`
	ManifestSHA256 string `json:"manifest_sha256"`
	Files          int    `json:"files"`
}

func tarPadding(size int64) int64 { return (-size) & (tarBlock - 1) }

// FormatPAX emits an ordinary USTAR header when possible, and otherwise uses
// only Go's deterministic path or size extensions for this header.
func fileHeader(name string, size int64) *tar.Header {
	return &tar.Header{Name: name, Size: size, Mode: 0600, Typeflag: tar.TypeReg, Format: tar.FormatPAX}
}

func readManifestFile(root *os.Root) ([]byte, error) {
	fd, size, err := openInput(root, archiveManifestName)
	if err != nil {
		return nil, errManifest
	}
	defer fd.Close()
	if size > maxManifest {
		return nil, errManifest
	}
	data, err := io.ReadAll(io.LimitReader(fd, size+1))
	if err != nil || int64(len(data)) != size {
		return nil, errManifest
	}
	return data, nil
}

func writeArchive(root *os.Root, raw []byte, manifest archiveManifest, output io.Writer) (int64, error) {
	info, err := root.Lstat("files")
	if err != nil || !info.IsDir() {
		return 0, errInput
	}
	files, err := root.OpenRoot("files")
	if err != nil {
		return 0, errInput
	}
	defer files.Close()
	bounded := &boundedWriter{out: output}
	out := tar.NewWriter(bounded)
	if out.WriteHeader(fileHeader(archiveManifestName, int64(len(raw)))) != nil {
		return 0, errArchiveOutput
	}
	if _, err := out.Write(raw); err != nil {
		return 0, errArchiveOutput
	}
	for _, entry := range manifest.Files {
		if err := writeArchiveEntry(files, out, entry); err != nil {
			return 0, err
		}
	}
	if out.Close() != nil {
		return 0, errArchiveOutput
	}
	return bounded.bytes, nil
}

func writeArchiveEntry(root *os.Root, out *tar.Writer, entry archiveFile) error {
	name := filepath.FromSlash(entry.Path)
	for parent := filepath.Dir(name); parent != "."; parent = filepath.Dir(parent) {
		info, err := root.Lstat(parent)
		if err != nil || !info.IsDir() {
			return errInput
		}
	}
	input, size, err := openInput(root, name)
	if err != nil {
		return errInput
	}
	defer input.Close()
	if size != entry.Size {
		return errArchiveIntegrity
	}
	if out.WriteHeader(fileHeader(entry.Path, size)) != nil {
		return errArchiveOutput
	}
	return copyArchiveEntry(out, io.LimitReader(input, size+1), entry)
}

func copyArchiveEntry(output io.Writer, input io.Reader, entry archiveFile) error {
	digest := sha256.New()
	n, err := io.Copy(io.MultiWriter(output, digest), input)
	if err != nil || n != entry.Size || hex.EncodeToString(digest.Sum(nil)) != entry.SHA256 {
		return errArchiveIntegrity
	}
	return nil
}

type archiveInput struct {
	*io.LimitedReader
	header []byte
}

func (source *archiveInput) Read(buffer []byte) (int, error) {
	if source.header == nil {
		return source.LimitedReader.Read(buffer)
	}
	remaining := 8192 - len(source.header)
	if remaining == 0 {
		return 0, errTar
	}
	n, err := source.LimitedReader.Read(buffer[:min(len(buffer), remaining)])
	source.header = append(source.header, buffer[:n]...)
	return n, err
}

func (source *archiveInput) next(in *tar.Reader) (*tar.Header, []byte, error) {
	source.header = make([]byte, 0, 2048)
	header, err := in.Next()
	wire := source.header
	source.header = nil
	return header, wire, err
}

// Next may interpret extensions and discard padding. Require the exact
// allowed encoding even when the parsed name and size happen to match.
func matchesHeader(wire []byte, name string, size, previous int64) bool {
	padding := int(tarPadding(previous))
	if len(wire) < padding || !allZero(wire[:padding]) {
		return false
	}
	var expected bytes.Buffer
	if tar.NewWriter(&expected).WriteHeader(fileHeader(name, size)) != nil {
		return false
	}
	return bytes.Equal(wire[padding:], expected.Bytes())
}

func allZero(data []byte) bool {
	for _, value := range data {
		if value != 0 {
			return false
		}
	}
	return true
}

func readArchive(input *os.File, size int64, destination *os.Root) (archiveReceipt, error) {
	source := &archiveInput{LimitedReader: &io.LimitedReader{R: input, N: size + 1}}
	in := tar.NewReader(source)
	header, wire, err := source.next(in)
	if err != nil || header.Size < 0 || header.Size > maxManifest ||
		!matchesHeader(wire, archiveManifestName, header.Size, 0) {
		return archiveReceipt{}, errTar
	}
	raw, err := io.ReadAll(in)
	if err != nil || int64(len(raw)) != header.Size {
		return archiveReceipt{}, errTar
	}
	manifest, err := validateManifest(raw)
	if err != nil {
		return archiveReceipt{}, err
	}
	if destination != nil {
		if err := stageManifest(destination, raw); err != nil {
			return archiveReceipt{}, err
		}
	}
	previous := header.Size
	for _, entry := range manifest.Files {
		_, wire, err := source.next(in)
		if err != nil || !matchesHeader(wire, entry.Path, entry.Size, previous) {
			return archiveReceipt{}, errTar
		}
		if err := readArchiveEntry(in, destination, entry); err != nil {
			return archiveReceipt{}, err
		}
		previous = entry.Size
	}
	_, wire, err = source.next(in)
	if err != io.EOF || int64(len(wire)) != tarPadding(previous)+2*tarBlock || !allZero(wire) || source.N != 1 {
		return archiveReceipt{}, errTar
	}
	if _, err := io.Copy(io.Discard, source); err != nil || source.N != 1 {
		return archiveReceipt{}, errTar
	}
	return archiveReceipt{"verified", size, fmt.Sprintf("%x", sha256.Sum256(raw)), len(manifest.Files)}, nil
}

func stageManifest(root *os.Root, raw []byte) error {
	fd, err := root.OpenFile(archiveManifestName, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errArchiveOutput
	}
	defer fd.Close()
	if _, err := fd.Write(raw); err != nil || fd.Sync() != nil || fd.Close() != nil ||
		root.Mkdir("files", 0700) != nil {
		return errArchiveOutput
	}
	return nil
}

func readArchiveEntry(input io.Reader, root *os.Root, entry archiveFile) error {
	if root == nil {
		return copyArchiveEntry(io.Discard, input, entry)
	}
	name := filepath.Join("files", filepath.FromSlash(entry.Path))
	if root.MkdirAll(filepath.Dir(name), 0700) != nil {
		return errArchiveOutput
	}
	fd, err := root.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errArchiveOutput
	}
	defer fd.Close()
	if err := copyArchiveEntry(fd, input, entry); err != nil {
		return err
	}
	if fd.Sync() != nil || fd.Close() != nil {
		return errArchiveOutput
	}
	return nil
}

func runArchive(args []string, result io.Writer) error {
	if len(args) != 3 || args[1] != "--directory" || !filepath.IsAbs(args[2]) {
		return errArguments
	}
	root, err := os.OpenRoot(args[2])
	if err != nil {
		return errDirectory
	}
	defer root.Close()
	if args[0] == "pack" {
		return packArchive(root, result)
	}
	input, size, err := openInput(root, "plaintext.tar.partial")
	if err != nil {
		return err
	}
	defer input.Close()
	if args[0] == "verify" {
		verified, err := readArchive(input, size, nil)
		if err != nil {
			return err
		}
		return reportArchive(result, verified)
	}
	return unpackArchive(root, input, size, result)
}

func packArchive(root *os.Root, result io.Writer) error {
	raw, err := readManifestFile(root)
	if err != nil {
		return err
	}
	manifest, err := validateManifest(raw)
	if err != nil {
		return err
	}
	output, err := root.OpenFile("plaintext.tar", os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errArchiveOutput
	}
	keep := false
	defer func() {
		output.Close()
		if !keep {
			root.Remove("plaintext.tar")
		}
	}()
	size, err := writeArchive(root, raw, manifest, output)
	if err != nil {
		return err
	}
	if output.Sync() != nil || output.Close() != nil {
		return errArchiveOutput
	}
	staged := archiveReceipt{"staged", size, fmt.Sprintf("%x", sha256.Sum256(raw)), len(manifest.Files)}
	if err := reportArchive(result, staged); err != nil {
		return err
	}
	keep = true
	return nil
}

func unpackArchive(root *os.Root, input *os.File, size int64, result io.Writer) error {
	if root.Mkdir(restoredDirectory, 0700) != nil {
		return errArchiveOutput
	}
	keep := false
	defer func() {
		if !keep {
			root.RemoveAll(restoredDirectory)
		}
	}()
	destination, err := root.OpenRoot(restoredDirectory)
	if err != nil {
		return errArchiveOutput
	}
	defer destination.Close()
	staged, err := readArchive(input, size, destination)
	if err != nil {
		return err
	}
	staged.State = "staged"
	if err := reportArchive(result, staged); err != nil {
		return err
	}
	keep = true
	return nil
}

func reportArchive(output io.Writer, result archiveReceipt) error {
	if json.NewEncoder(output).Encode(result) != nil {
		return errArchiveOutput
	}
	return nil
}
