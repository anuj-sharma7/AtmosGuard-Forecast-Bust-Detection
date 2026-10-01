/**
 * Risk presentation helpers.
 *
 * The risk colours are a *status* palette, not a categorical one: green through
 * red is an ordered severity scale that no single-hue ramp can express, and it
 * is the colour convention operational forecasters already read. Because the
 * hues are not colour-vision-safe against one another (green vs red in
 * particular), every place a risk colour appears it is accompanied by the
 * category label, and on the map risk is redundantly encoded by marker radius.
 * Colour never carries the meaning alone.
 */

import type { RiskCategory } from '../api/types';

export const RISK_COLORS: Record<RiskCategory, string> = {
  LOW: '#0ca30c',
  MODERATE: '#fab219',
  HIGH: '#ec835a',
  SEVERE: '#d03b3b',
};

/** Chart series colours, validated against the #0d1524 panel surface. */
export const SERIES = {
  primary: '#3987e5',
  secondary: '#199e70',
  tertiary: '#d95926',
  /** Observations are truth, not a model: they wear ink, not a series hue. */
  observed: '#e8eef7',
  member: '#3987e5',
};

export const RISK_ORDER: RiskCategory[] = ['LOW', 'MODERATE', 'HIGH', 'SEVERE'];

export function riskColor(category: RiskCategory): string {
  return RISK_COLORS[category] ?? RISK_COLORS.LOW;
}

export function categoryFor(score: number): RiskCategory {
  if (score <= 30) return 'LOW';
  if (score <= 60) return 'MODERATE';
  if (score <= 80) return 'HIGH';
  return 'SEVERE';
}

/** Tailwind classes for a risk chip. Kept as literals so Tailwind can see them. */
export function riskChipClass(category: RiskCategory): string {
  switch (category) {
    case 'LOW':
      return 'border-risk-low/45 bg-risk-low/12 text-risk-low';
    case 'MODERATE':
      return 'border-risk-moderate/45 bg-risk-moderate/12 text-risk-moderate';
    case 'HIGH':
      return 'border-risk-high/45 bg-risk-high/12 text-risk-high';
    case 'SEVERE':
      return 'border-risk-severe/45 bg-risk-severe/12 text-risk-severe';
  }
}

/** Marker radius on the map - the redundant encoding for the risk colour. */
export function markerRadius(score: number, featured: boolean): number {
  return (featured ? 6.5 : 4.5) + (score / 100) * (featured ? 7.5 : 5.5);
}

export const RISK_DEFINITION =
  'How likely the selected medium-range forecast is to deviate significantly from the eventual observed outcome. ' +
  'This is a calibrated 0-100 risk index rather than a raw probability - see the Verification page for the observed bust rate within each band.';
