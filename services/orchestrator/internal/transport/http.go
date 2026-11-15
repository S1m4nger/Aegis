package transport

import (
	"aegis/orchestrator/internal/config"
	"aegis/orchestrator/internal/domain"
	"aegis/orchestrator/internal/orchestrator"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"go.uber.org/fx"
	"go.uber.org/zap"
)

func jsonError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
func recoverJSON(log *zap.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if recover() != nil {
					log.Error("request panic", zap.String("request_id", middleware.GetReqID(r.Context())))
					jsonError(w, http.StatusInternalServerError, "internal server error")
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}
func NewRouter(s *orchestrator.Service, log *zap.Logger) http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID, recoverJSON(log))
	r.Post("/v1/simulate", simulateFrozen)
	r.Get("/health/live", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"alive":true}`))
	})
	r.Get("/health/ready", func(w http.ResponseWriter, r *http.Request) {
		if !s.Ready(r.Context()) {
			jsonError(w, 503, "scorer not ready")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ready":true}`))
	})
	r.Post("/v1/analyze", func(w http.ResponseWriter, r *http.Request) {
		now := time.Now()
		r.Body = http.MaxBytesReader(w, r.Body, 64*1024)
		dec := json.NewDecoder(r.Body)
		dec.DisallowUnknownFields()
		var input struct {
			Step   *int     `json:"step"`
			Type   *string  `json:"type"`
			Amount *float64 `json:"amount"`
		}
		if err := dec.Decode(&input); err != nil {
			jsonError(w, 400, "invalid JSON or transaction fields")
			return
		}
		var extra any
		if err := dec.Decode(&extra); !errors.Is(err, io.EOF) {
			jsonError(w, 400, "only one JSON object allowed")
			return
		}
		if input.Step == nil || input.Type == nil || input.Amount == nil {
			jsonError(w, 400, "step, type and amount are required")
			return
		}
		tx := domain.Transaction{Step: *input.Step, Type: *input.Type, Amount: *input.Amount}
		if err := tx.Validate(); err != nil {
			jsonError(w, 400, err.Error())
			return
		}
		out, err := s.Analyze(r.Context(), tx)
		if err != nil {
			log.Warn("analysis unavailable", zap.String("request_id", middleware.GetReqID(r.Context())), zap.Error(err))
			jsonError(w, 503, "analysis unavailable")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(out)
		log.Info("analysis completed", zap.String("request_id", middleware.GetReqID(r.Context())), zap.String("model_version", out.ModelVersion), zap.String("policy_version", out.PolicyVersion), zap.String("conflict", out.ConflictType), zap.String("action", out.RecommendedAction), zap.Duration("duration", time.Since(now)))
	})
	return r
}
func NewServer(cfg config.Config, h http.Handler) *http.Server {
	return &http.Server{
		Addr: cfg.HTTPAddr, Handler: h, ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 10 * time.Second,
		WriteTimeout: 10 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 1 << 20,
	}
}
func RegisterLifecycle(lc fx.Lifecycle, s *http.Server, log *zap.Logger) {
	var listener net.Listener
	lc.Append(fx.Hook{
		OnStart: func(ctx context.Context) error {
			l, err := net.Listen("tcp", s.Addr)
			if err != nil {
				return err
			}
			listener = l
			go func() {
				err := s.Serve(listener)
				if err != nil && !errors.Is(err, http.ErrServerClosed) {
					log.Error("http server error", zap.Error(err))
				}
			}()
			log.Info("Aegis Go API listening", zap.String("address", s.Addr))
			return nil
		},
		OnStop: func(ctx context.Context) error { return s.Shutdown(ctx) },
	})
}
