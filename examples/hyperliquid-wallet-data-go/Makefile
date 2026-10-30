MODULE := github.com/dwellir-public/dwellir-examples/examples/hyperliquid-wallet-data-go/internal/hlpb

.PHONY: proto build vet

# Regenerate internal/hlpb from proto/v3.proto.
proto:
	protoc -I proto \
		--go_out=internal/hlpb --go_opt=paths=source_relative --go_opt=Mv3.proto=$(MODULE) \
		--go-grpc_out=internal/hlpb --go-grpc_opt=paths=source_relative --go-grpc_opt=Mv3.proto=$(MODULE) \
		v3.proto

build:
	go build -o bin/ ./cmd/...

vet:
	go vet ./...
