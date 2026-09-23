# networkops (Go)

Hand-written Go client for the NetworkOps Manager API - standard library only, Go >= 1.23
(range-over-func iterators).

```bash
go get github.com/tecsys-sol/decixtacs/sdk/go/networkops
```

```go
ctx := context.Background()
c, err := networkops.New("https://nom.example.net", networkops.WithToken(os.Getenv("NOM_TOKEN")))
// or: networkops.WithPassword("alice", pw, "acme"), networkops.WithOTP(totpFunc)
if err != nil {
	log.Fatal(err)
}

// every Juniper device, pagination handled by the iterator
for dev, err := range c.Devices.All(ctx, &networkops.DeviceListOptions{Vendor: "juniper"}) {
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(dev.Hostname, dev.ManagementIP)
}

// what changed on a device since the previous backup, with risk analysis
diff, err := c.Backups.Diff(ctx, deviceID, networkops.DiffOptions{Old: "HEAD~1"})

// publish the TACACS+ configuration
rev, err := c.Tacacs.Deploy(ctx, serverID)

// commands matching a regex in the last 24 h
since := time.Now().Add(-24 * time.Hour)
page, err := c.Accounting.Search(ctx, &networkops.CommandSearch{Command: "~^request system", Start: &since})

// change workflow; errors are *APIError with helpers
_, err = c.Changes.Transition(ctx, changeID, "approve", "CAB ok", true)
if networkops.IsConflict(err) { /* e.g. four-eyes rule */ }

// endpoints without a helper
var members []map[string]any
err = c.Do(ctx, http.MethodGet, "/ixp/members", url.Values{"q": {"AS13335"}}, nil, &members)
```

Behaviour: password sessions refresh the access token 30 s before expiry with the rotating
refresh token (and log in again if it was revoked); idempotent requests are retried on
transport errors and 429/502/503/504 (`WithMaxRetries`); `WithActAsTenant` sends `X-Tenant`
for platform superusers. Run the tests with `go test -race ./...`.
