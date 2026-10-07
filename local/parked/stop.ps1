# Stops Mercury's local rung. A local run queued while it is down ends in
# error with "providers unavailable" and never falls back to a cloud rung.
tailscale funnel reset
Get-Process caddy -ErrorAction SilentlyContinue | Stop-Process
