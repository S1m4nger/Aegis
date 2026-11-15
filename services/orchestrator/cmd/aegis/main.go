package main

import (
	"aegis/orchestrator/internal/config"
	"aegis/orchestrator/internal/logging"
	"aegis/orchestrator/internal/mlclient"
	"aegis/orchestrator/internal/orchestrator"
	"aegis/orchestrator/internal/policy"
	"aegis/orchestrator/internal/rules"
	"aegis/orchestrator/internal/transport"
	"go.uber.org/fx"
)

func main() {
	fx.New(
		fx.Provide(
			config.Load,
			logging.New,
			rules.New,
			policy.Load,
			fx.Annotate(mlclient.New, fx.As(new(orchestrator.Scorer))),
			orchestrator.New,
			transport.NewRouter,
			transport.NewServer,
		),
		fx.Invoke(transport.RegisterLifecycle),
	).Run()
}
