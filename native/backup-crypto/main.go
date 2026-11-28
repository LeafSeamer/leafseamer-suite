package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"filippo.io/age"
)

const (
	maxArchive    = 64 << 30
	maxHeader     = 64 << 10
	maxSecret     = 16 << 10
	maxRecipients = 16
	workFactor    = 18
)

var (
	errArguments  = errors.New("backup_crypto_arguments")
	errSecret     = errors.New("backup_crypto_secret")
	errDirectory  = errors.New("backup_crypto_directory")
	errInput      = errors.New("backup_crypto_input")
	errOutput     = errors.New("backup_crypto_output")
	errCiphertext = errors.New("backup_crypto_ciphertext")
	errProfile    = errors.New("backup_crypto_profile")
	errLimit      = errors.New("backup_crypto_limit")
)

type recipients []string

func (r *recipients) String() string { return "" }

func (r *recipients) Set(value string) error {
	if len(*r) == maxRecipients {
		return errProfile
	}
	*r = append(*r, value)
	return nil
}

type options struct {
	seal            bool
	mode, directory string
	recipients      recipients
	bytes           int64
	sha256          string
	manifestSHA256  string
	destination     string
}

func parse(args []string) (options, error) {
	var opts options
	if len(args) == 0 || (args[0] != "seal" && args[0] != "open") {
		return opts, errArguments
	}
	opts.seal = args[0] == "seal"
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.StringVar(&opts.mode, "mode", "", "")
	flags.StringVar(&opts.directory, "directory", "", "")
	if opts.seal {
		flags.Var(&opts.recipients, "recipient", "")
		flags.StringVar(&opts.manifestSHA256, "manifest-sha256", "", "")
		flags.StringVar(&opts.destination, "destination", "", "")
	} else {
		flags.Int64Var(&opts.bytes, "expected-bytes", 0, "")
		flags.StringVar(&opts.sha256, "expected-sha256", "", "")
	}
	if flags.Parse(args[1:]) != nil || flags.NArg() != 0 ||
		(opts.mode != "x25519" && opts.mode != "passphrase") ||
		!filepath.IsAbs(opts.directory) || filepath.Clean(opts.directory) != opts.directory {
		return opts, errArguments
	}
	if opts.seal {
		if (opts.mode == "x25519") != (len(opts.recipients) != 0) {
			return opts, errProfile
		}
		if opts.destination != "" || opts.manifestSHA256 != "" {
			if !filepath.IsAbs(opts.destination) || filepath.Clean(opts.destination) != opts.destination ||
				opts.destination == opts.directory || !hexDigest(opts.manifestSHA256) {
				return opts, errArguments
			}
		}
		return opts, nil
	}
	digest, err := hex.DecodeString(opts.sha256)
	if err != nil || len(digest) != sha256.Size || strings.ToLower(opts.sha256) != opts.sha256 ||
		opts.bytes <= 0 || opts.bytes > maxArchive {
		return opts, errCiphertext
	}
	return opts, nil
}

func readSecret(pipe *os.File) ([]byte, error) {
	info, err := pipe.Stat()
	if err != nil || (info.Mode()&os.ModeNamedPipe == 0 && !inheritedLocalStream(pipe, info.Mode())) {
		return nil, errSecret
	}
	value, err := io.ReadAll(io.LimitReader(pipe, maxSecret+1))
	if err != nil || len(value) == 0 || len(value) > maxSecret {
		clear(value)
		return nil, errSecret
	}
	return value, nil
}

func (opts options) encryptTo(pipe *os.File) ([]age.Recipient, error) {
	if opts.mode == "passphrase" {
		secret, err := readSecret(pipe)
		if err != nil {
			return nil, err
		}
		defer clear(secret)
		r, err := age.NewScryptRecipient(string(secret))
		if err != nil {
			return nil, errSecret
		}
		r.SetWorkFactor(workFactor)
		return []age.Recipient{r}, nil
	}
	seen := make(map[string]bool)
	result := make([]age.Recipient, 0, len(opts.recipients))
	for _, key := range opts.recipients {
		r, err := age.ParseX25519Recipient(key)
		if err != nil || seen[r.String()] {
			return nil, errProfile
		}
		seen[r.String()] = true
		result = append(result, r)
	}
	return result, nil
}

type profileIdentity struct {
	age.Identity
	stanzaType string
	maxStanzas int
}

func (p profileIdentity) Unwrap(stanzas []*age.Stanza) ([]byte, error) {
	if len(stanzas) == 0 || len(stanzas) > p.maxStanzas {
		return nil, errProfile
	}
	for _, stanza := range stanzas {
		if stanza.Type != p.stanzaType {
			return nil, errProfile
		}
	}
	return p.Identity.Unwrap(stanzas)
}

func (opts options) decryptWith(pipe *os.File) (age.Identity, error) {
	secret, err := readSecret(pipe)
	if err != nil {
		return nil, err
	}
	defer clear(secret)
	if opts.mode == "passphrase" {
		id, err := age.NewScryptIdentity(string(secret))
		if err != nil {
			return nil, errSecret
		}
		id.SetMaxWorkFactor(workFactor)
		return profileIdentity{id, "scrypt", 1}, nil
	}
	id, err := age.ParseX25519Identity(string(secret))
	if err != nil {
		return nil, errSecret
	}
	return profileIdentity{id, "X25519", maxRecipients}, nil
}

func openInput(root *os.Root, name string) (*os.File, int64, error) {
	before, err := root.Lstat(name)
	if err != nil || !before.Mode().IsRegular() || before.Size() > maxArchive {
		return nil, 0, errInput
	}
	file, err := root.Open(name)
	if err != nil {
		return nil, 0, errInput
	}
	opened, err := file.Stat()
	if err != nil || !os.SameFile(before, opened) || before.Size() != opened.Size() {
		file.Close()
		return nil, 0, errInput
	}
	return file, opened.Size(), nil
}

type boundedWriter struct {
	out   io.Writer
	bytes int64
}

func (w *boundedWriter) Write(p []byte) (int, error) {
	if int64(len(p)) > maxArchive-w.bytes {
		return 0, errLimit
	}
	n, err := w.out.Write(p)
	w.bytes += int64(n)
	return n, err
}

type receipt struct {
	State  string `json:"state"`
	Bytes  int64  `json:"ciphertext_bytes"`
	SHA256 string `json:"ciphertext_sha256"`
}

func seal(opts options, secret, input *os.File, size int64, output *os.File) (receipt, error) {
	var archiveHash string
	if opts.manifestSHA256 != "" {
		hash := sha256.New()
		archive, err := readArchive(io.TeeReader(input, hash), size, nil)
		if err != nil || archive.ManifestSHA256 != opts.manifestSHA256 {
			return receipt{}, errManifest
		}
		if _, err := input.Seek(0, io.SeekStart); err != nil {
			return receipt{}, errInput
		}
		archiveHash = hex.EncodeToString(hash.Sum(nil))
	}
	keys, err := opts.encryptTo(secret)
	if err != nil {
		return receipt{}, err
	}
	digest := sha256.New()
	sink := &boundedWriter{out: io.MultiWriter(output, digest)}
	encrypted, err := age.Encrypt(sink, keys...)
	if err != nil {
		return receipt{}, errOutput
	}
	var archiveInput io.Reader = io.LimitReader(input, size+1)
	plaintextHash := sha256.New()
	if archiveHash != "" {
		archiveInput = io.TeeReader(archiveInput, plaintextHash)
	}
	n, err := io.Copy(encrypted, archiveInput)
	if err != nil || n != size {
		return receipt{}, errInput
	}
	if archiveHash != "" && hex.EncodeToString(plaintextHash.Sum(nil)) != archiveHash {
		return receipt{}, errArchiveIntegrity
	}
	if encrypted.Close() != nil {
		return receipt{}, errOutput
	}
	return receipt{"staged", sink.bytes, hex.EncodeToString(digest.Sum(nil))}, nil
}

func open(opts options, secret, input *os.File, size int64, output *os.File) (receipt, error) {
	id, err := opts.decryptWith(secret)
	if err != nil {
		return receipt{}, err
	}
	digest := sha256.New()
	headerBudget := min(size+1, maxHeader)
	source := &io.LimitedReader{R: io.TeeReader(input, digest), N: headerBudget}
	plain, err := age.Decrypt(source, id)
	if err != nil {
		return receipt{}, errCiphertext
	}
	// Keep bytes already consumed by the decoder's buffered header read in the hash.
	source.N += size + 1 - headerBudget
	if _, err := io.Copy(&boundedWriter{out: output}, plain); err != nil {
		return receipt{}, errCiphertext
	}
	if source.N != 1 || hex.EncodeToString(digest.Sum(nil)) != opts.sha256 {
		return receipt{}, errCiphertext
	}
	return receipt{"staged", opts.bytes, opts.sha256}, nil
}

func run(args []string, secret *os.File, result io.Writer) error {
	if len(args) > 0 && (args[0] == "pack" || args[0] == "verify" || args[0] == "unpack") {
		return runArchive(args, result)
	}
	opts, err := parse(args)
	if err != nil {
		return err
	}
	root, err := os.OpenRoot(opts.directory)
	if err != nil {
		return errDirectory
	}
	defer root.Close()
	inputName, outputName, transform := "ciphertext.age", "plaintext.tar.partial", open
	if opts.seal {
		inputName, outputName, transform = "plaintext.tar", "ciphertext.age.partial", seal
	}
	input, size, err := openInput(root, inputName)
	if err != nil {
		return err
	}
	defer input.Close()
	if !opts.seal && size != opts.bytes {
		return errCiphertext
	}
	target := root
	if opts.destination != "" {
		target, err = os.OpenRoot(opts.destination)
		if err != nil {
			return errDirectory
		}
		defer target.Close()
		outputName = "archive.age"
	}
	output, err := target.OpenFile(outputName, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errOutput
	}
	keep := false
	defer func() {
		if !keep {
			output.Close()
			target.Remove(outputName)
		}
	}()
	staged, err := transform(opts, secret, input, size, output)
	if err != nil {
		return err
	}
	if output.Sync() != nil || output.Close() != nil {
		return errOutput
	}
	if opts.destination != "" {
		parent, err := os.OpenRoot(filepath.Dir(opts.destination))
		if err != nil {
			return errOutput
		}
		defer parent.Close()
		if syncArchiveDirectory(target) != nil || syncArchiveDirectory(parent) != nil {
			return errOutput
		}
	}
	if json.NewEncoder(result).Encode(staged) != nil {
		return errOutput
	}
	keep = true
	return nil
}

func main() {
	timer := time.AfterFunc(30*time.Minute, func() {
		io.WriteString(os.Stderr, "backup_crypto_deadline\n")
		os.Exit(1)
	})
	defer timer.Stop()
	if err := run(os.Args[1:], os.Stdin, os.Stdout); err != nil {
		io.WriteString(os.Stderr, err.Error()+"\n")
		os.Exit(1)
	}
}
