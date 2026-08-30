/**
 * Deterministic growth-objective telemetry, matching src/edgecraft/growth.py.
 * Display-only: the $100k target never overrides risk policy.
 */
import { asNumber } from "./numbers";
import type { Fund, GrowthSnapshot, GrowthStage } from "./types";

const DEFAULT_TARGET_NAV = 100_000;
const DEFAULT_HORIZON_YEARS = 10;

export function growthObjectiveFromMandate(fund: Fund): {
  targetNav: number;
  targetHorizonYears: number;
} {
  const mandate = fund.mandate ?? {};
  const raw = mandate.growth_objective;
  const objective =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  return {
    targetNav: asNumber(objective.target_nav as string | number | undefined, DEFAULT_TARGET_NAV),
    targetHorizonYears: asNumber(
      objective.target_horizon_years as string | number | undefined,
      DEFAULT_HORIZON_YEARS,
    ),
  };
}

export function buildGrowthSnapshot(
  initialNav: number,
  currentNav: number,
  objective: { targetNav: number; targetHorizonYears: number },
): GrowthSnapshot {
  const targetNav = objective.targetNav > 0 ? objective.targetNav : DEFAULT_TARGET_NAV;
  const years =
    objective.targetHorizonYears > 0
      ? objective.targetHorizonYears
      : DEFAULT_HORIZON_YEARS;
  const start = initialNav > 0 ? initialNav : 1;
  const nav = Number.isFinite(currentNav) ? currentNav : start;

  const targetMultiple = targetNav / start;
  const remainingMultiple = nav > 0 ? targetNav / nav : targetMultiple;
  const denom = targetNav - start;
  const simpleProgress =
    denom > 0 ? clamp01((nav - start) / denom) : nav >= targetNav ? 1 : 0;

  let logProgress = 0;
  if (nav <= start || targetMultiple <= 1) {
    logProgress = nav < targetNav ? 0 : 1;
  } else {
    const logTarget = Math.log(targetMultiple);
    logProgress =
      logTarget === 0 ? 0 : clamp01(Math.log(nav / start) / logTarget);
  }

  const requiredAnnualReturn =
    years > 0 ? Math.pow(targetMultiple, 1 / years) - 1 : 0;
  const multiple = nav / start;

  let stage: GrowthStage;
  if (nav >= targetNav) stage = "objective_reached";
  else if (multiple < 2) stage = "bootstrap";
  else if (multiple < 10) stage = "compound";
  else if (multiple < 50) stage = "scale";
  else stage = "protect";

  return {
    stage,
    initialNav: start,
    currentNav: nav,
    targetNav,
    targetHorizonYears: years,
    targetMultiple,
    remainingMultiple,
    simpleProgress,
    logProgress,
    requiredAnnualReturn,
    objectiveReached: nav >= targetNav,
  };
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}
