// 층별 구조도 이미지 출처: 순천향대학교 천안병원 공식 홈페이지
// (https://www.schmc.ac.kr/cheonan/contents.do?key=16186), 비상업적 캡스톤 시연용.

export type FloorNumber = 1 | 2 | 3 | 4 | 5;

export type FloorMapInfo = {
  floor: FloorNumber;
  label: string;
  imagePath: string;
};

export const FLOOR_MAPS: FloorMapInfo[] = [
  { floor: 1, label: '1층', imagePath: '/images/floor-maps/1f.jpg' },
  { floor: 2, label: '2층', imagePath: '/images/floor-maps/2f.png' },
  { floor: 3, label: '3층', imagePath: '/images/floor-maps/3f.png' },
  { floor: 4, label: '4층', imagePath: '/images/floor-maps/4f.png' },
  { floor: 5, label: '5층', imagePath: '/images/floor-maps/5f.png' },
];

export function getFloorMapInfo(floor: FloorNumber): FloorMapInfo {
  const info = FLOOR_MAPS.find((f) => f.floor === floor);
  if (!info) {
    throw new Error(`알 수 없는 층입니다: ${floor}`);
  }
  return info;
}
