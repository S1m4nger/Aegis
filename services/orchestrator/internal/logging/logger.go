package logging

import (
	"context"
	"errors"
	"go.uber.org/fx"
	"go.uber.org/zap"
	"syscall"
)

func New(lc fx.Lifecycle) (*zap.Logger, error) {
	l, err := zap.NewProduction()
	if err != nil {
		return nil, err
	}
	lc.Append(fx.Hook{OnStop: func(ctx context.Context) error {
		err := l.Sync()
		if errors.Is(err, syscall.EINVAL) || errors.Is(err, syscall.ENOTTY) {
			return nil // stderr may be a terminal or pipe without fsync support.
		}
		return err
	}})
	return l, nil
}
