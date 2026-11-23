package main

import (
	"context"
	"flag"
	"io"
	"os"
	"time"

	collector "github.com/LeafSeamer/leafseamer-suite/native/reference-time"
)

func run(arguments []string) int {
	options := flag.NewFlagSet("reference-time-provider", flag.ContinueOnError)
	options.SetOutput(io.Discard)
	intent := options.String("intent", "", "")
	domain := options.String("domain", "", "")
	timeout := options.Int("timeout-ms", 0, "")
	coreReceipt := options.String("core-receipt-id", "", "")
	database := options.String("database-instance", "", "")
	if err := options.Parse(arguments); err != nil || options.NArg() != 0 || *timeout < 1 || *timeout > 60000 ||
		*coreReceipt == "" || *database == "" {
		return 1
	}
	limit := time.Duration(*timeout) * time.Millisecond
	admission, err := collector.BootstrapTimeProvider(context.Background(), os.Stdin, os.Stdout,
		collector.ProviderLaunch{Intent: []byte(*intent), Descriptor: []byte(*domain), Timeout: limit})
	if err != nil {
		return 1
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stopped := make(chan bool, 1)
	go func() {
		var unexpected [1]byte
		n, err := os.Stdin.Read(unexpected[:])
		stopped <- n == 0 && err == io.EOF
		cancel()
	}()
	_ = collector.RunProviderLink(ctx, admission, *coreReceipt, *database, limit)
	select {
	case orderly := <-stopped:
		if orderly {
			return 0
		}
	default:
	}
	return 1
}

func main() { os.Exit(run(os.Args[1:])) }
