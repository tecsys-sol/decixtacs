// Package networkops is a hand-written client for the NetworkOps Manager REST API (/api/v1).
//
// It uses only the standard library (net/http, context, encoding/json).
//
//	c, err := networkops.New("https://nom.example.net", networkops.WithToken("nomt_..."))
//	if err != nil { ... }
//	for dev, err := range c.Devices.All(ctx, &networkops.DeviceListOptions{Vendor: "juniper"}) {
//		if err != nil { ... }
//		fmt.Println(dev.Hostname, dev.ManagementIP)
//	}
//
// Authentication is either an API token (WithToken) or username/password (WithPassword): the
// client then logs in lazily, refreshes the short-lived access token before it expires using the
// rotating refresh token and logs in again if the refresh token was revoked.
//
// Errors returned for non-2xx responses are *APIError values; use IsNotFound, IsConflict, ... or
// errors.As to inspect them. Idempotent requests are retried on transport errors and
// 429/502/503/504.
package networkops
