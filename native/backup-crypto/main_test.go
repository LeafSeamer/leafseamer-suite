package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"testing"

	"filippo.io/age"
)

func invoke(t *testing.T, secret []byte, args ...string) (receipt, error) {
	t.Helper()
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer writer.Close()
		writer.Write(secret)
	}()
	var stdout bytes.Buffer
	err = run(args, reader, &stdout)
	reader.Close()
	<-done
	if err != nil {
		if stdout.Len() != 0 {
			t.Fatal("failed operation returned a receipt")
		}
		return receipt{}, err
	}
	var staged receipt
	if err := json.Unmarshal(stdout.Bytes(), &staged); err != nil {
		t.Fatal(err)
	}
	return staged, nil
}

func writeFile(t *testing.T, directory, name string, data []byte) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(directory, name), data, 0600); err != nil {
		t.Fatal(err)
	}
}

func readFile(t *testing.T, directory, name string) []byte {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(directory, name))
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func absent(t *testing.T, directory, name string) {
	t.Helper()
	if _, err := os.Lstat(filepath.Join(directory, name)); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("%s should be absent: %v", name, err)
	}
}

func openArgs(directory, mode string, ciphertext []byte) []string {
	return []string{"open", "--directory", directory, "--mode", mode,
		"--expected-bytes", strconv.Itoa(len(ciphertext)),
		"--expected-sha256", fmt.Sprintf("%x", sha256.Sum256(ciphertext))}
}

func identity(t *testing.T) *age.X25519Identity {
	t.Helper()
	id, err := age.GenerateX25519Identity()
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func roundTrip(t *testing.T, mode string, sealingOptions []string, sealingSecret, openingSecret []byte) []byte {
	t.Helper()
	directory := t.TempDir()
	plaintext := bytes.Repeat([]byte("temporary archive content"), 9000)
	writeFile(t, directory, "plaintext.tar", plaintext)
	args := append([]string{"seal", "--directory", directory, "--mode", mode}, sealingOptions...)
	staged, err := invoke(t, sealingSecret, args...)
	if err != nil {
		t.Fatal(err)
	}
	absent(t, directory, "ciphertext.age")
	raw := readFile(t, directory, "ciphertext.age.partial")
	if staged != (receipt{"staged", int64(len(raw)), fmt.Sprintf("%x", sha256.Sum256(raw))}) {
		t.Fatal("seal receipt does not identify the staged ciphertext")
	}

	restore := t.TempDir()
	writeFile(t, restore, "ciphertext.age", raw)
	opened, err := invoke(t, openingSecret, openArgs(restore, mode, raw)...)
	if err != nil || opened != staged {
		t.Fatalf("open receipt = %+v, %v", opened, err)
	}
	if !bytes.Equal(readFile(t, restore, "plaintext.tar.partial"), plaintext) {
		t.Fatal("staged plaintext differs")
	}
	absent(t, restore, "plaintext.tar")
	return raw
}

func TestX25519(t *testing.T) {
	first, second := identity(t), identity(t)
	raw := roundTrip(t, "x25519", []string{"--recipient", first.Recipient().String(),
		"--recipient", second.Recipient().String()}, nil, []byte(second.String()))
	directory := t.TempDir()
	writeFile(t, directory, "ciphertext.age", raw)
	args := openArgs(directory, "x25519", raw)
	wrongDigest := append([]string(nil), args...)
	wrongDigest[len(wrongDigest)-1] = fmt.Sprintf("%064x", 0)
	wrongLength := append([]string(nil), args...)
	wrongLength[len(wrongLength)-3] = strconv.Itoa(len(raw) - 1)
	for _, test := range []struct {
		name   string
		secret []byte
		args   []string
	}{
		{"different recipient", []byte(identity(t).String()), args},
		{"different digest", []byte(first.String()), wrongDigest},
		{"different size", []byte(first.String()), wrongLength},
		{"different mode", []byte(first.String()), openArgs(directory, "passphrase", raw)},
	} {
		t.Run(test.name, func(t *testing.T) {
			if _, err := invoke(t, test.secret, test.args...); !errors.Is(err, errCiphertext) {
				t.Fatalf("unexpected result: %v", err)
			}
			absent(t, directory, "plaintext.tar.partial")
		})
	}
	for _, changed := range [][]byte{
		append(bytes.Clone(raw), 'x'), raw[:len(raw)-1],
		append(bytes.Clone(raw[:len(raw)-1]), raw[len(raw)-1]^1),
	} {
		writeFile(t, directory, "ciphertext.age", changed)
		if _, err := invoke(t, []byte(first.String()), openArgs(directory, "x25519", changed)...); !errors.Is(err, errCiphertext) {
			t.Fatalf("invalid ciphertext accepted: %v", err)
		}
		absent(t, directory, "plaintext.tar.partial")
	}
}

func TestPassphrase(t *testing.T) {
	secret := []byte("密码\n末尾空格 ")
	raw := roundTrip(t, "passphrase", nil, secret, secret)
	highCost := bytes.Replace(raw, []byte(" 18\n"), []byte(" 19\n"), 1)
	if bytes.Equal(raw, highCost) {
		t.Fatal("ciphertext did not advertise scrypt logN 18")
	}
	directory := t.TempDir()
	writeFile(t, directory, "ciphertext.age", highCost)
	if _, err := invoke(t, secret, openArgs(directory, "passphrase", highCost)...); !errors.Is(err, errCiphertext) {
		t.Fatalf("excessive KDF work was accepted: %v", err)
	}
	absent(t, directory, "plaintext.tar.partial")
	writeFile(t, directory, "ciphertext.age", raw)
	if _, err := invoke(t, []byte("different secret"), openArgs(directory, "passphrase", raw)...); !errors.Is(err, errCiphertext) {
		t.Fatalf("different passphrase was accepted: %v", err)
	}
	absent(t, directory, "plaintext.tar.partial")
}

func TestStagingAndSecretRestrictions(t *testing.T) {
	directory := t.TempDir()
	writeFile(t, directory, "plaintext.tar", []byte("archive"))
	args := []string{"seal", "--directory", directory, "--mode", "passphrase"}
	for _, secret := range [][]byte{nil, make([]byte, maxSecret+1)} {
		if _, err := invoke(t, secret, args...); !errors.Is(err, errSecret) {
			t.Fatalf("wrong secret size accepted: %v", err)
		}
		absent(t, directory, "ciphertext.age.partial")
	}
	input, err := os.Open(filepath.Join(directory, "plaintext.tar"))
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	if err := run(args, input, &bytes.Buffer{}); !errors.Is(err, errSecret) {
		t.Fatalf("regular file accepted as secret channel: %v", err)
	}
	key := identity(t).Recipient().String()
	publicArgs := []string{"seal", "--directory", directory, "--mode", "x25519", "--recipient", key}
	duplicate := append(append([]string(nil), publicArgs...), "--recipient", key)
	if _, err := invoke(t, nil, duplicate...); !errors.Is(err, errProfile) {
		t.Fatalf("duplicate key accepted: %v", err)
	}
	writeFile(t, directory, "ciphertext.age.partial", []byte("prior artifact"))
	if _, err := invoke(t, nil, publicArgs...); !errors.Is(err, errOutput) {
		t.Fatalf("staged file not protected: %v", err)
	}
	if string(readFile(t, directory, "ciphertext.age.partial")) != "prior artifact" {
		t.Fatal("overwrote an existing staged file")
	}
}

func TestUnsupportedCiphertextProfile(t *testing.T) {
	id := identity(t)
	recipients := make([]age.Recipient, maxRecipients+1)
	for i := range recipients {
		recipients[i] = id.Recipient()
	}
	var ciphertext bytes.Buffer
	writer, err := age.Encrypt(&ciphertext, recipients...)
	if err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	directory := t.TempDir()
	raw := ciphertext.Bytes()
	writeFile(t, directory, "ciphertext.age", raw)
	if _, err := invoke(t, []byte(id.String()), openArgs(directory, "x25519", raw)...); !errors.Is(err, errCiphertext) {
		t.Fatalf("excessive recipients were accepted: %v", err)
	}
	absent(t, directory, "plaintext.tar.partial")
}
