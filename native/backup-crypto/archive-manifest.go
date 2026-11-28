package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"path"
	"slices"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

const (
	archiveManifestName = "manifest.json"
	archiveFormat       = "leafseamer-backup-tar/1"
	maxManifest         = 16 << 20
	maxEntry            = 32 << 30
	maxEntries          = 100000
)

var (
	errManifest    = errors.New("backup_archive_manifest")
	errArchivePath = errors.New("backup_archive_path")
)

type archiveFile struct {
	Role   string `json:"role"`
	Path   string `json:"path"`
	Size   int64  `json:"size"`
	SHA256 string `json:"sha256"`
}

type archiveDatabase struct {
	Path             string `json:"path"`
	Service          string `json:"service"`
	DatabaseInstance string `json:"database_instance"`
	Schema           string `json:"schema"`
	Engine           string `json:"engine"`
	ConsistencyPoint string `json:"consistency_point"`
}

type archiveCoverage struct {
	Kind      string `json:"kind"`
	Reference string `json:"reference"`
	State     string `json:"state"`
	Path      string `json:"path"`
}

type archiveManifest struct {
	Format            string            `json:"format"`
	BackupID          string            `json:"backup_id"`
	Level             string            `json:"level"`
	Consistency       string            `json:"consistency"`
	Files             []archiveFile     `json:"files"`
	Databases         []archiveDatabase `json:"databases"`
	Coverage          []archiveCoverage `json:"coverage"`
	Unresolved        []string          `json:"unresolved"`
	ValidationReports []string          `json:"validation_reports"`
}

var minimumLevel = map[string]int{
	"release": 0, "template": 0,
	"configuration": 1, "definition": 1, "catalog": 1, "module_approval": 1, "validation_report": 1,
	"database": 2, "audit": 2, "unresolved": 2, "nodecg": 2, "log": 2,
	"secret": 3,
}

func reference(value string) bool {
	return len(value) <= 256 && value != "" && strings.TrimSpace(value) == value &&
		!strings.ContainsFunc(value, unicode.IsControl)
}

func hexDigest(value string) bool {
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && value == strings.ToLower(value)
}

func portableArchivePath(value string) bool {
	if value == "" || len(value) > 1024 || !utf8.ValidString(value) || path.Clean(value) != value {
		return false
	}
	for _, part := range strings.Split(value, "/") {
		if part == "" || part == "." || part == ".." || len(part) > 255 ||
			strings.HasSuffix(part, ".") || strings.HasSuffix(part, " ") ||
			strings.ContainsAny(part, `\:*?"<>|`) || strings.ContainsFunc(part, unicode.IsControl) {
			return false
		}
		stem, _, _ := strings.Cut(part, ".")
		stem = strings.ToUpper(strings.TrimRight(stem, " "))
		switch stem {
		case "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$":
			return false
		}
		if prefix, rest := stem[:min(len(stem), 3)], stem[min(len(stem), 3):]; (prefix == "COM" || prefix == "LPT") &&
			rest != "" && strings.Contains("123456789¹²³", rest) && utf8.RuneCountInString(rest) == 1 {
			return false
		}
	}
	return true
}

func foldArchiveName(value string) string {
	return strings.Map(func(letter rune) rune {
		smallest := letter
		for folded := unicode.SimpleFold(letter); folded != letter; folded = unicode.SimpleFold(folded) {
			smallest = min(smallest, folded)
		}
		return smallest
	}, value)
}

func uniqueArchivePaths(files []archiveFile) bool {
	type archivePath struct {
		parts  []string
		folded []string
	}
	paths := make([]archivePath, 0, len(files)+1)
	add := func(value string) {
		paths = append(paths, archivePath{strings.Split(value, "/"), strings.Split(foldArchiveName(value), "/")})
	}
	add(archiveManifestName)
	for _, file := range files {
		add(file.Path)
	}
	sort.Slice(paths, func(i, j int) bool { return slices.Compare(paths[i].folded, paths[j].folded) < 0 })
	for i := 1; i < len(paths); i++ {
		left, right := paths[i-1], paths[i]
		shared := 0
		for shared < min(len(left.parts), len(right.parts)) && left.folded[shared] == right.folded[shared] {
			if left.parts[shared] != right.parts[shared] {
				return false
			}
			shared++
		}
		if shared == min(len(left.parts), len(right.parts)) {
			return false
		}
	}
	return true
}

func validateManifest(raw []byte) (archiveManifest, error) {
	var manifest archiveManifest
	if len(raw) > maxManifest || !utf8.Valid(raw) ||
		json.Unmarshal(raw, &manifest) != nil {
		return manifest, errManifest
	}
	canonical, err := json.Marshal(manifest)
	if err != nil || !bytes.Equal(raw, canonical) || manifest.Format != archiveFormat ||
		!reference(manifest.BackupID) || len(manifest.Files) == 0 || len(manifest.Files)+1 > maxEntries ||
		manifest.Databases == nil || manifest.Coverage == nil || manifest.Unresolved == nil || manifest.ValidationReports == nil {
		return manifest, errManifest
	}
	level := slices.Index([]string{"L0", "L1", "L2", "L3"}, manifest.Level)
	if level < 0 || (manifest.Consistency != "online" && manifest.Consistency != "maintenance") {
		return manifest, errManifest
	}

	roles := make(map[string]string, len(manifest.Files))
	counts := make(map[string]int)
	total := tarBlock*3 + int64(len(raw)) + tarPadding(int64(len(raw)))
	previous := ""
	for _, entry := range manifest.Files {
		if !portableArchivePath(entry.Path) || entry.Path <= previous {
			return manifest, errArchivePath
		}
		previous = entry.Path
		minimum, known := minimumLevel[entry.Role]
		if !known || level < minimum || entry.Size < 0 || entry.Size > maxEntry || !hexDigest(entry.SHA256) {
			return manifest, errManifest
		}
		total += tarBlock + entry.Size + tarPadding(entry.Size)
		if total > maxArchive {
			return manifest, errLimit
		}
		roles[entry.Path] = entry.Role
		counts[entry.Role]++
	}
	if !uniqueArchivePaths(manifest.Files) {
		return manifest, errArchivePath
	}
	if !validateArchiveDatabases(manifest.Databases, roles, counts["database"]) ||
		!validateArchiveCoverage(manifest.Coverage, roles, counts["secret"]) ||
		!validateManifestReferences(manifest.Unresolved, reference) ||
		len(manifest.ValidationReports) != counts["validation_report"] ||
		!validateManifestReferences(manifest.ValidationReports, func(value string) bool { return roles[value] == "validation_report" }) {
		return manifest, errManifest
	}
	return manifest, nil
}

func validateManifestReferences(values []string, valid func(string) bool) bool {
	seen := make(map[string]bool, len(values))
	for _, value := range values {
		if !valid(value) || seen[value] {
			return false
		}
		seen[value] = true
	}
	return true
}

func validateArchiveDatabases(databases []archiveDatabase, roles map[string]string, count int) bool {
	if len(databases) != count {
		return false
	}
	paths := make(map[string]bool, count)
	identities := make(map[[2]string]bool, count)
	for _, db := range databases {
		identity := [2]string{db.Service, db.DatabaseInstance}
		if roles[db.Path] != "database" || paths[db.Path] || identities[identity] ||
			!reference(db.Service) || !reference(db.DatabaseInstance) || !reference(db.Schema) ||
			!reference(db.Engine) || !reference(db.ConsistencyPoint) {
			return false
		}
		paths[db.Path], identities[identity] = true, true
	}
	return true
}

func validateArchiveCoverage(coverage []archiveCoverage, roles map[string]string, secretCount int) bool {
	references := make(map[[2]string]bool, len(coverage))
	secrets := make(map[string]bool, secretCount)
	for _, entry := range coverage {
		role, known := map[string]string{"component": "release", "configuration": "configuration", "secret": "secret"}[entry.Kind]
		identity := [2]string{entry.Kind, entry.Reference}
		if !known || !reference(entry.Reference) || references[identity] {
			return false
		}
		references[identity] = true
		switch entry.State {
		case "included":
			if roles[entry.Path] != role {
				return false
			}
			if entry.Kind == "secret" {
				if secrets[entry.Path] {
					return false
				}
				secrets[entry.Path] = true
			}
		case "missing", "excluded":
			if entry.Path != "" {
				return false
			}
		default:
			return false
		}
	}
	return len(secrets) == secretCount
}
