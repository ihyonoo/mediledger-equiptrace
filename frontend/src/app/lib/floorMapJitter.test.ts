import { describe, it, expect } from 'vitest';
import { jitterOffset, clampPct } from './floorMapJitter';

describe('jitterOffset', () => {
  it('returns the same offset for the same tag id every call', () => {
    const first = jitterOffset('EQ-0001', 2);
    const second = jitterOffset('EQ-0001', 2);
    expect(second).toEqual(first);
  });

  it('returns different offsets for different tag ids', () => {
    const a = jitterOffset('EQ-0001', 2);
    const b = jitterOffset('EQ-0002', 2);
    expect(a).not.toEqual(b);
  });

  it('never exceeds the given radius', () => {
    for (let i = 0; i < 200; i += 1) {
      const { dx, dy } = jitterOffset(`EQ-${i}`, 2);
      const distance = Math.sqrt(dx * dx + dy * dy);
      expect(distance).toBeLessThanOrEqual(2 + 1e-9);
    }
  });

  it('spreads offsets across the disk instead of collapsing to the edge or center', () => {
    const distances = Array.from({ length: 100 }, (_, i) => {
      const { dx, dy } = jitterOffset(`EQ-${i}`, 2);
      return Math.sqrt(dx * dx + dy * dy);
    });
    const nearCenter = distances.filter((d) => d < 0.5).length;
    const nearEdge = distances.filter((d) => d > 1.5).length;
    expect(nearCenter).toBeGreaterThan(0);
    expect(nearEdge).toBeGreaterThan(0);
  });
});

describe('clampPct', () => {
  it('clamps values below 0 up to 0', () => {
    expect(clampPct(-5)).toBe(0);
  });

  it('clamps values above 100 down to 100', () => {
    expect(clampPct(120)).toBe(100);
  });

  it('leaves in-range values untouched', () => {
    expect(clampPct(42.5)).toBe(42.5);
  });
});
