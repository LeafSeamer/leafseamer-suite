package main

import (
	"archive/tar"
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func archiveEntry(name, role string, data []byte) archiveFile {
	return archiveFile{role, name, int64(len(data)), fmt.Sprintf("%x", sha256.Sum256(data))}
}

func manifestFor(entries ...archiveFile) archiveManifest {
	return archiveManifest{archiveFormat, "fixture.backup", "L0", "online", entries,
		[]archiveDatabase{}, []archiveCoverage{}, []string{}, []string{}}
}

func manifestBytes(t *testing.T, manifest archiveManifest) []byte {
	t.Helper()
	raw, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func invokeArchive(t *testing.T, verb, directory string) (archiveReceipt, error) {
	t.Helper()
	var output bytes.Buffer
	if err := run([]string{verb, "--directory", directory}, nil, &output); err != nil {
		if output.Len() != 0 {
			t.Fatal("failed archive operation returned a receipt")
		}
		return archiveReceipt{}, err
	}
	var result archiveReceipt
	if err := json.Unmarshal(output.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	return result, nil
}

func putArchiveInput(t *testing.T, directory, name string, body []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(directory, "files", filepath.Dir(name)), 0700); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(directory, "files"), name, body)
}

func TestArchiveEncryptedRoundTrip(t *testing.T) {
	staging, restore := t.TempDir(), t.TempDir()
	name := "config/" + strings.Repeat("编", 40) + "/definition.json"
	contents := []byte("synthetic definition")
	db := []byte("synthetic database snapshot")
	password := []byte("synthetic stored secret")
	manifest := manifestFor(archiveEntry(name, "definition", contents),
		archiveEntry("db/fixture.sqlite", "database", db), archiveEntry("secrets/one", "secret", password))
	manifest.Level = "L3"
	manifest.Consistency = "maintenance"
	manifest.Databases = []archiveDatabase{{"db/fixture.sqlite", "controller", "db.fixture", "schema.1", "sqlite.fixture", "capture.1"}}
	manifest.Coverage = []archiveCoverage{{"secret", "secret.one", "included", "secrets/one"}, {"secret", "secret.two", "missing", ""}}
	manifest.Unresolved = []string{"command.unknown"}
	raw := manifestBytes(t, manifest)
	writeFile(t, staging, archiveManifestName, raw)
	putArchiveInput(t, staging, name, contents)
	putArchiveInput(t, staging, "db/fixture.sqlite", db)
	putArchiveInput(t, staging, "secrets/one", password)

	staged, err := invokeArchive(t, "pack", staging)
	if err != nil || staged.State != "staged" || staged.ArchiveBytes < 1024 || staged.Files != 3 ||
		staged.ManifestSHA256 != fmt.Sprintf("%x", sha256.Sum256(raw)) {
		t.Fatalf("pack: %+v, %v", staged, err)
	}
	id := identity(t)
	if _, err := invoke(t, nil, "seal", "--directory", staging, "--mode", "x25519", "--recipient", id.Recipient().String()); err != nil {
		t.Fatal(err)
	}
	ciphertext := readFile(t, staging, "ciphertext.age.partial")
	writeFile(t, restore, "ciphertext.age", ciphertext)
	if _, err := invoke(t, []byte(id.String()), openArgs(restore, "x25519", ciphertext)...); err != nil {
		t.Fatal(err)
	}
	verified, err := invokeArchive(t, "verify", restore)
	if err != nil || verified != (archiveReceipt{"verified", staged.ArchiveBytes, staged.ManifestSHA256, 3}) {
		t.Fatalf("verify: %+v, %v", verified, err)
	}
	absent(t, restore, restoredDirectory)
	unpacked, err := invokeArchive(t, "unpack", restore)
	if err != nil || unpacked != staged {
		t.Fatalf("unpack: %+v, %v", unpacked, err)
	}
	root := filepath.Join(restore, restoredDirectory)
	if !bytes.Equal(readFile(t, root, archiveManifestName), raw) ||
		!bytes.Equal(readFile(t, filepath.Join(root, "files"), name), contents) ||
		!bytes.Equal(readFile(t, filepath.Join(root, "files"), "db/fixture.sqlite"), db) ||
		!bytes.Equal(readFile(t, filepath.Join(root, "files"), "secrets/one"), password) {
		t.Fatal("unpacked bytes differ")
	}
	if _, err := invokeArchive(t, "unpack", restore); !errors.Is(err, errArchiveOutput) {
		t.Fatalf("existing stage was reused: %v", err)
	}
}

func TestArchiveManifestRejectsInvalidSelection(t *testing.T) {
	template := func(name string) archiveFile { return archiveEntry(name, "template", nil) }
	for _, paths := range [][]string{
		{"../escape"}, {"/absolute"}, {"device/CON.txt"}, {"device/COM¹.txt"}, {"device/branch "},
		{"file", "file-elsewhere", "file/child"}, {"Dir/a", "dir/b"}, {"Σ", "ς"},
		{"MANIFEST.JSON"}, {"repeat", "repeat"}, {"victim:stream"}, {"drive\\file"},
	} {
		entries := make([]archiveFile, 0, len(paths))
		for _, name := range paths {
			entries = append(entries, template(name))
		}
		if _, err := validateManifest(manifestBytes(t, manifestFor(entries...))); !errors.Is(err, errArchivePath) {
			t.Fatalf("invalid paths %q accepted: %v", paths, err)
		}
	}
	first, second := template("first"), template("second")
	first.Size, second.Size = maxEntry, maxEntry
	if _, err := validateManifest(manifestBytes(t, manifestFor(first, second))); !errors.Is(err, errLimit) {
		t.Fatalf("excessive expanded bytes accepted: %v", err)
	}
	manifest := manifestFor(archiveEntry("state.sqlite", "database", nil))
	manifest.Level = "L2"
	if _, err := validateManifest(manifestBytes(t, manifest)); !errors.Is(err, errManifest) {
		t.Fatalf("database missing consistent point accepted: %v", err)
	}
	manifest = manifestFor(archiveEntry("private", "secret", nil))
	manifest.Level = "L3"
	if _, err := validateManifest(manifestBytes(t, manifest)); !errors.Is(err, errManifest) {
		t.Fatalf("secret missing explicit coverage accepted: %v", err)
	}
	canonical := manifestBytes(t, manifestFor(template("file")))
	duplicate := append([]byte(`{"format":"shadow",`), canonical[1:]...)
	if _, err := validateManifest(duplicate); !errors.Is(err, errManifest) {
		t.Fatalf("duplicate manifest key accepted: %v", err)
	}
}

func TestArchiveHeaderAtPathAndFileLimits(t *testing.T) {
	name := strings.Repeat(strings.Repeat("界", 84)+"/", 4) + strings.Repeat("x", 12)
	if len(name) != 1024 || !portableArchivePath(name) || portableArchivePath(name+"x") {
		t.Fatal("incorrect portable path limit")
	}
	var header bytes.Buffer
	if err := tar.NewWriter(&header).WriteHeader(fileHeader(name, maxEntry)); err != nil {
		t.Fatal(err)
	}
	source := &archiveInput{LimitedReader: &io.LimitedReader{R: &header, N: int64(header.Len())}}
	decoded, wire, err := source.next(tar.NewReader(source))
	if err != nil || decoded.Name != name || decoded.Size != maxEntry || !matchesHeader(wire, name, maxEntry, 0) {
		t.Fatalf("maximum supported TAR header failed: %v", err)
	}
}

func archiveFixture(t *testing.T, manifest []byte, headers []*tar.Header, body []byte) []byte {
	t.Helper()
	var result bytes.Buffer
	writer := tar.NewWriter(&result)
	items := append([]*tar.Header{fileHeader(archiveManifestName, int64(len(manifest)))}, headers...)
	for i, header := range items {
		if err := writer.WriteHeader(header); err != nil {
			t.Fatal(err)
		}
		if header.Size > 0 {
			data := body
			if i == 0 {
				data = manifest
			}
			if _, err := writer.Write(data); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return result.Bytes()
}

func TestRejectedArchiveLeavesNoRestoreStage(t *testing.T) {
	payload := []byte("fixture data")
	entry := archiveEntry("record", "template", payload)
	manifest := manifestBytes(t, manifestFor(entry))
	valid := fileHeader(entry.Path, entry.Size)
	good := archiveFixture(t, manifest, []*tar.Header{valid}, payload)
	pax := fileHeader(entry.Path, entry.Size)
	pax.PAXRecords = map[string]string{"fixture.extra": "ignored metadata"}
	gnu := fileHeader(entry.Path, entry.Size)
	gnu.Format = tar.FormatGNU
	pad := bytes.Clone(good)
	pad[tarBlock+len(manifest)] = 1
	for _, test := range []struct {
		name string
		data []byte
	}{
		{"missing", archiveFixture(t, manifest, nil, nil)},
		{"duplicate", archiveFixture(t, manifest, []*tar.Header{valid, valid}, payload)},
		{"traversal", archiveFixture(t, manifest, []*tar.Header{fileHeader("../record", entry.Size)}, payload)},
		{"symlink", archiveFixture(t, manifest, []*tar.Header{{Name: "record", Typeflag: tar.TypeSymlink, Linkname: "../outside"}}, nil)},
		{"hard link", archiveFixture(t, manifest, []*tar.Header{{Name: "record", Typeflag: tar.TypeLink, Linkname: "elsewhere"}}, nil)},
		{"device", archiveFixture(t, manifest, []*tar.Header{{Name: "record", Typeflag: tar.TypeChar}}, nil)},
		{"extra PAX", archiveFixture(t, manifest, []*tar.Header{pax}, payload)},
		{"GNU", archiveFixture(t, manifest, []*tar.Header{gnu}, payload)},
		{"changed data", archiveFixture(t, manifest, []*tar.Header{valid}, bytes.Repeat([]byte{'x'}, len(payload)))},
		{"truncated", good[:len(good)-tarBlock]},
		{"trailing zeros", append(bytes.Clone(good), make([]byte, tarBlock)...)},
		{"nonzero padding", pad},
	} {
		t.Run(test.name, func(t *testing.T) {
			directory := t.TempDir()
			writeFile(t, directory, "plaintext.tar.partial", test.data)
			writeFile(t, directory, "record", []byte("sentinel"))
			if _, err := invokeArchive(t, "unpack", directory); err == nil {
				t.Fatal("invalid TAR was accepted")
			}
			absent(t, directory, restoredDirectory)
			if string(readFile(t, directory, "record")) != "sentinel" {
				t.Fatal("changed file outside restore stage")
			}
		})
	}
}

func TestPackRejectsChangedSourceAndPreservesExistingOutput(t *testing.T) {
	directory := t.TempDir()
	body := []byte("original")
	writeFile(t, directory, archiveManifestName, manifestBytes(t, manifestFor(archiveEntry("record", "template", body))))
	putArchiveInput(t, directory, "record", []byte("changed!"))
	if _, err := invokeArchive(t, "pack", directory); !errors.Is(err, errArchiveIntegrity) {
		t.Fatalf("changed source was accepted: %v", err)
	}
	absent(t, directory, "plaintext.tar")
	writeFile(t, directory, "plaintext.tar", body)
	if _, err := invokeArchive(t, "pack", directory); !errors.Is(err, errArchiveOutput) ||
		!bytes.Equal(readFile(t, directory, "plaintext.tar"), body) {
		t.Fatalf("preexisting TAR was replaced: %v", err)
	}
}
