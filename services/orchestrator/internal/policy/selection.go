package policy

import (
	"errors"
	"math"
	"sort"
)

// Observation is selection-window evidence. Fraud is consumed only by the
// offline optimizers; capacity ranking uses Score and Step only.
type Observation struct {
	Score float64
	Fraud bool
	Step  int
}

func validateObservations(observations []Observation) error {
	if len(observations) == 0 {
		return errors.New("selection observations are empty")
	}
	hasFraud, hasLegitimate := false, false
	for _, observation := range observations {
		if math.IsNaN(observation.Score) || math.IsInf(observation.Score, 0) || observation.Score < 0 || observation.Score > 1 {
			return errors.New("selection score must be finite and in [0,1]")
		}
		if observation.Step < 1 {
			return errors.New("selection step must be positive")
		}
		if observation.Fraud {
			hasFraud = true
		} else {
			hasLegitimate = true
		}
	}
	if !hasFraud || !hasLegitimate {
		return errors.New("selection observations must contain both classes")
	}
	return nil
}

type scoredIndex struct {
	score float64
	index int
}

// OptimizeClassification chooses the selection threshold maximizing F1.
// Exact F1 ties prefer fewer false positives, then the higher threshold.
func OptimizeClassification(observations []Observation) (float64, error) {
	if err := validateObservations(observations); err != nil {
		return 0, err
	}

	ordered := make([]scoredIndex, len(observations))
	positives := 0
	for index, observation := range observations {
		ordered[index] = scoredIndex{score: observation.Score, index: index}
		if observation.Fraud {
			positives++
		}
	}
	sort.Slice(ordered, func(i, j int) bool {
		if ordered[i].score == ordered[j].score {
			return ordered[i].index < ordered[j].index
		}
		return ordered[i].score > ordered[j].score
	})

	thresholds := map[float64]struct{}{1: {}}
	for _, item := range ordered {
		if item.score > 0 {
			thresholds[item.score] = struct{}{}
		}
	}
	candidates := make([]float64, 0, len(thresholds))
	for threshold := range thresholds {
		candidates = append(candidates, threshold)
	}
	sort.Sort(sort.Reverse(sort.Float64Slice(candidates)))

	bestThreshold := candidates[0]
	var bestNumerator, bestDenominator int64
	var bestFalsePositives int64
	position := 0
	truePositives, falsePositives := int64(0), int64(0)
	for candidateIndex, threshold := range candidates {
		for position < len(ordered) && ordered[position].score >= threshold {
			if observations[ordered[position].index].Fraud {
				truePositives++
			} else {
				falsePositives++
			}
			position++
		}
		falseNegatives := int64(positives) - truePositives
		numerator := 2 * truePositives
		denominator := numerator + falsePositives + falseNegatives
		if denominator == 0 {
			continue
		}
		better := candidateIndex == 0 || numerator*bestDenominator > bestNumerator*denominator
		tied := numerator*bestDenominator == bestNumerator*denominator
		if better || (tied && (falsePositives < bestFalsePositives ||
			(falsePositives == bestFalsePositives && threshold > bestThreshold))) {
			bestThreshold = threshold
			bestNumerator = numerator
			bestDenominator = denominator
			bestFalsePositives = falsePositives
		}
	}
	return bestThreshold, nil
}

var costThresholdGrid = []float64{
	0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1,
	0.2, 0.4, 0.6, 0.8, 0.999, 1,
}

var costQuantiles = []float64{0.50, 0.75, 0.90, 0.95, 0.99}

func thresholdCandidates(observations []Observation) []float64 {
	scores := make([]float64, len(observations))
	for i, observation := range observations {
		scores[i] = observation.Score
	}
	sort.Float64s(scores)
	unique := make(map[float64]struct{}, len(costThresholdGrid)+len(costQuantiles))
	for _, threshold := range costThresholdGrid {
		unique[threshold] = struct{}{}
	}
	for _, quantile := range costQuantiles {
		position := quantile * float64(len(scores)-1)
		lower := int(math.Floor(position))
		fraction := position - float64(lower)
		value := scores[lower]
		if lower+1 < len(scores) {
			value += fraction * (scores[lower+1] - value)
		}
		if value > 0 && value <= 1 {
			unique[value] = struct{}{}
		}
	}
	candidates := make([]float64, 0, len(unique))
	for threshold := range unique {
		candidates = append(candidates, threshold)
	}
	sort.Float64s(candidates)
	return candidates
}

func actionsForThresholds(observations []Observation, reviewThreshold, flagThreshold float64) []string {
	actions := make([]string, len(observations))
	for index, observation := range observations {
		switch {
		case observation.Score >= flagThreshold:
			actions[index] = "FLAG"
		case observation.Score >= reviewThreshold:
			actions[index] = "REVIEW"
		default:
			actions[index] = "APPROVE"
		}
	}
	return actions
}

// OptimizeCosts searches a deterministic bounded threshold grid on selection
// labels. The configured classification threshold is copied through unchanged.
func OptimizeCosts(observations []Observation, base Config, scenario Scenario) (Config, error) {
	if err := validateObservations(observations); err != nil {
		return Config{}, err
	}
	if err := base.Validate(); err != nil {
		return Config{}, err
	}
	if err := scenario.Validate(); err != nil {
		return Config{}, err
	}
	if base.Strategy == AlwaysLegitimate {
		return base, nil
	}
	candidates := thresholdCandidates(observations)
	best := base
	bestLoss := math.Inf(1)
	for _, reviewThreshold := range candidates {
		for _, flagThreshold := range candidates {
			if reviewThreshold >= flagThreshold {
				continue
			}
			actions := actionsForThresholds(observations, reviewThreshold, flagThreshold)
			actions = ApplyCapacity(observations, actions, scenario.CapacityPer1000)
			totalLoss := 0.0
			for index, observation := range observations {
				totalLoss += scenario.Loss(observation.Fraud, actions[index])
			}
			if totalLoss < bestLoss {
				bestLoss = totalLoss
				best.ReviewThreshold = reviewThreshold
				best.FlagThreshold = flagThreshold
			}
		}
	}
	if math.IsInf(bestLoss, 1) {
		return Config{}, errors.New("no valid review/flag threshold pair")
	}
	return best, nil
}

// ApplyCapacity caps REVIEW actions per simulation step. Ranking depends only
// on the supplied scores; original row order breaks ties deterministically.
func ApplyCapacity(observations []Observation, actions []string, per1000 int) []string {
	result := append([]string(nil), actions...)
	if len(observations) != len(actions) || per1000 <= 0 {
		if per1000 <= 0 && len(observations) == len(actions) {
			for index, action := range result {
				if action == "REVIEW" {
					result[index] = "APPROVE"
				}
			}
		}
		return result
	}
	if per1000 > 1000 {
		per1000 = 1000
	}
	byStep := make(map[int][]int)
	for index, action := range result {
		if action == "REVIEW" {
			byStep[observations[index].Step] = append(byStep[observations[index].Step], index)
		}
	}
	stepSizes := make(map[int]int)
	for _, observation := range observations {
		stepSizes[observation.Step]++
	}
	for step, reviewIndexes := range byStep {
		budget := stepSizes[step] * per1000 / 1000
		sort.Slice(reviewIndexes, func(i, j int) bool {
			left, right := reviewIndexes[i], reviewIndexes[j]
			if observations[left].Score == observations[right].Score {
				return left < right
			}
			return observations[left].Score > observations[right].Score
		})
		if budget < len(reviewIndexes) {
			for _, index := range reviewIndexes[budget:] {
				result[index] = "APPROVE"
			}
		}
	}
	return result
}
