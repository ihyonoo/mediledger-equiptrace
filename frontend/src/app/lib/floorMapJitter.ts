// 방(reader) 좌표 하나에 여러 장비가 몰려도 지도에서 겹치지 않도록, 태그별로 결정적인
// 작은 오프셋을 준다. 실제 위치 판정 해상도가 room 단위임을 정직하게 반영하기 위해
// 오프셋 반경(maxPct)은 항상 작게 유지한다 — 넓게 흩어지면 "정밀 위치 추적"처럼 오해된다.

function fnv1a(input: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function jitterOffset(tagId: string, maxPct: number): { dx: number; dy: number } {
  const angleSeed = fnv1a(tagId) % 100000;
  const radiusSeed = fnv1a(`${tagId}:r`) % 100000;
  const angle = (angleSeed / 100000) * 2 * Math.PI;
  // sqrt로 반지름을 뽑아야 원판(disk) 전체에 균일하게 분포한다(그냥 곱하면 중심에 쏠림).
  const radius = Math.sqrt(radiusSeed / 100000) * maxPct;
  return { dx: radius * Math.cos(angle), dy: radius * Math.sin(angle) };
}

export function clampPct(value: number): number {
  return Math.min(100, Math.max(0, value));
}
