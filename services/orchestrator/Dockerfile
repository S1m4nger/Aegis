# syntax=docker/dockerfile:1.7
FROM --platform=$BUILDPLATFORM golang:1.27.3-bookworm@sha256:dc0963f32053e4bc451d24d87e3892d42d01021b61f093e98eb95c0352bb84b0 AS builder
ARG TARGETOS
ARG TARGETARCH
ENV GOTOOLCHAIN=local
WORKDIR /build
COPY services/orchestrator/go.mod services/orchestrator/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download && go mod verify
COPY services/orchestrator/cmd/aegis ./cmd/aegis
COPY services/orchestrator/internal ./internal
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -mod=readonly -trimpath -buildvcs=false -ldflags="-s -w -buildid=" -o /out/aegis ./cmd/aegis
# A small static probe avoids adding a shell, curl or wget to the runtime image.
RUN <<'EOF'
cat > /tmp/healthcheck.go <<'GO'
package main

import (
    "net/http"
    "os"
    "time"
)

func main() {
    client := &http.Client{Timeout: 3*time.Second, CheckRedirect: func(*http.Request, []*http.Request) error {
        return http.ErrUseLastResponse
    }}
    response, err := client.Get("http://127.0.0.1:8080/health/ready")
    if err != nil {
        os.Exit(1)
    }
    defer response.Body.Close()
    if response.StatusCode != http.StatusOK {
        os.Exit(1)
    }
}
GO
gofmt -w /tmp/healthcheck.go
CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -buildvcs=false -ldflags="-s -w -buildid=" -o /out/healthcheck /tmp/healthcheck.go
EOF

FROM scratch AS runtime
WORKDIR /app
COPY --from=builder /out/aegis /out/healthcheck /app/
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --chown=10001:10001 configs/rules.json configs/policy.json /app/configs/
ENV AEGIS_HTTP_ADDR=0.0.0.0:8080 \
    AEGIS_ML_URL=http://ml:8091 \
    AEGIS_RULES_PATH=/app/configs/rules.json \
    AEGIS_POLICY_PATH=/app/configs/policy.json
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 CMD ["/app/healthcheck"]
ENTRYPOINT ["/app/aegis"]
