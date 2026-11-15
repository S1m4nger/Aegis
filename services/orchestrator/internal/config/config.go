package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPAddr   string
	MLURL      string
	RulesPath  string
	PolicyPath string
	MLTimeout  time.Duration
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func Load() Config {
	millis, err := strconv.Atoi(getenv("AEGIS_ML_TIMEOUT_MS", "2500"))
	if err != nil || millis < 100 || millis > 10000 {
		millis = 2500
	}
	return Config{
		HTTPAddr:   getenv("AEGIS_HTTP_ADDR", "127.0.0.1:8080"),
		MLURL:      getenv("AEGIS_ML_URL", "http://127.0.0.1:8091"),
		RulesPath:  getenv("AEGIS_RULES_PATH", "../../configs/rules.json"),
		PolicyPath: getenv("AEGIS_POLICY_PATH", "../../configs/policy.json"),
		MLTimeout:  time.Duration(millis) * time.Millisecond,
	}
}
