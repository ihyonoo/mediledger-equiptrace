import { useCallback, useRef, useState, type ReactNode } from 'react';
import { getFloorMapInfo, type FloorNumber } from '../lib/floorMaps';
import { clampPct, jitterOffset } from '../lib/floorMapJitter';

export type FloorMapPin = {
  reader_id: string;
  label: string;
  map_x: number;
  map_y: number;
  badge?: ReactNode;
};

export type FloorMapEquipmentDot = {
  tag_id: string;
  reader_id: string;
  label: string;
  assetStatus?: string;
  badge?: ReactNode;
};

// 목록·상세 화면과 같은 상태 색상 토큰을 쓴다(theme.css). 대여 중은 빨강 계열이라
// 지도만 봐도 쓸 수 있는 장비와 나가 있는 장비가 바로 구분된다.
const ASSET_STATUS_DOT: Record<string, { className: string; label: string }> = {
  checked_out: { className: 'dot-err', label: '대여 중' },
  maintenance: { className: 'dot-warn', label: '점검 중' },
  inactive: { className: 'solid-neutral', label: '비활성' },
  available: { className: 'dot-ok', label: '사용 가능' },
};

function assetStatusDot(status: string | undefined) {
  return ASSET_STATUS_DOT[status ?? 'available'] ?? ASSET_STATUS_DOT.available;
}

type FloorMapViewProps = {
  floor: FloorNumber;
  pins: FloorMapPin[];
  equipment?: FloorMapEquipmentDot[];
  onEquipmentClick?: (tagId: string) => void;
  onPinClick?: (readerId: string) => void;
  onPinMoved?: (readerId: string, mapX: number, mapY: number) => void;
  pendingReaderId?: string | null;
  onPendingPlace?: (mapX: number, mapY: number) => void;
  jitterMaxPct?: number;
  // 구역 표식은 좌표를 배치·확인하는 관리자 핀 편집기에서만 필요하다. 직원용 지도에서는
  // 평면도에 이미 구역명이 인쇄돼 있어 장비 점만 그린다.
  showPins?: boolean;
};

function percentFromEvent(container: HTMLElement, clientX: number, clientY: number) {
  const rect = container.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return { x: 0, y: 0 };
  return {
    x: clampPct(((clientX - rect.left) / rect.width) * 100),
    y: clampPct(((clientY - rect.top) / rect.height) * 100),
  };
}

export default function FloorMapView({
  floor,
  pins,
  equipment = [],
  onEquipmentClick,
  onPinClick,
  onPinMoved,
  pendingReaderId = null,
  onPendingPlace,
  jitterMaxPct = 1.75,
  showPins = false,
}: FloorMapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [draggingReaderId, setDraggingReaderId] = useState<string | null>(null);
  const [dragPct, setDragPct] = useState<{ x: number; y: number } | null>(null);
  const floorInfo = getFloorMapInfo(floor);

  const handleContainerClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!pendingReaderId || !onPendingPlace || !containerRef.current) return;
      if ((event.target as HTMLElement).closest('[data-floor-map-pin]')) return;
      const pct = percentFromEvent(containerRef.current, event.clientX, event.clientY);
      onPendingPlace(pct.x, pct.y);
    },
    [pendingReaderId, onPendingPlace],
  );

  const handlePinMouseDown = useCallback(
    (readerId: string) => (event: React.MouseEvent) => {
      if (!onPinMoved) return;
      event.stopPropagation();
      setDraggingReaderId(readerId);
    },
    [onPinMoved],
  );

  const handleContainerMouseMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!draggingReaderId || !containerRef.current) return;
      setDragPct(percentFromEvent(containerRef.current, event.clientX, event.clientY));
    },
    [draggingReaderId],
  );

  const stopDragging = useCallback(() => {
    if (draggingReaderId && dragPct && onPinMoved) {
      onPinMoved(draggingReaderId, dragPct.x, dragPct.y);
    }
    setDraggingReaderId(null);
    setDragPct(null);
  }, [draggingReaderId, dragPct, onPinMoved]);

  const equipmentByReader = new Map<string, FloorMapEquipmentDot[]>();
  for (const dot of equipment) {
    const list = equipmentByReader.get(dot.reader_id) ?? [];
    list.push(dot);
    equipmentByReader.set(dot.reader_id, list);
  }

  return (
    <div
      ref={containerRef}
      data-testid="floor-map-container"
      className="relative w-full select-none overflow-hidden rounded-lg border border-border bg-card"
      onClick={handleContainerClick}
      onMouseMove={handleContainerMouseMove}
      onMouseUp={stopDragging}
      onMouseLeave={stopDragging}
    >
      <img src={floorInfo.imagePath} alt={`${floorInfo.label} 평면도`} className="block w-full" draggable={false} />

      {(showPins ? pins : []).map((pin) => {
        const isDragging = draggingReaderId === pin.reader_id;
        const x = isDragging && dragPct ? dragPct.x : pin.map_x;
        const y = isDragging && dragPct ? dragPct.y : pin.map_y;
        return (
          <button
            key={pin.reader_id}
            type="button"
            data-floor-map-pin
            data-testid={`floor-map-pin-${pin.reader_id}`}
            // 구역명은 평면도 이미지에 이미 인쇄돼 있으므로 핀은 표식만 그리고
            // 이름은 툴팁(title)으로만 노출한다.
            title={pin.label}
            aria-label={pin.label}
            className="absolute -translate-x-1/2 -translate-y-1/2 h-3.5 w-3.5 rounded-full border-2 border-primary bg-background shadow-sm"
            style={{ left: `${x}%`, top: `${y}%`, cursor: onPinMoved ? 'grab' : 'pointer' }}
            onMouseDown={handlePinMouseDown(pin.reader_id)}
            onClick={(event) => {
              event.stopPropagation();
              onPinClick?.(pin.reader_id);
            }}
          >
            {pin.badge ? <span className="absolute -right-1.5 -top-1.5">{pin.badge}</span> : null}
          </button>
        );
      })}

      {pins.map((pin) => {
        const dots = equipmentByReader.get(pin.reader_id) ?? [];
        return dots.map((dot) => {
          const { dx, dy } = jitterOffset(dot.tag_id, jitterMaxPct);
          const x = clampPct(pin.map_x + dx);
          const y = clampPct(pin.map_y + dy);
          const status = assetStatusDot(dot.assetStatus);
          return (
            <button
              key={dot.tag_id}
              type="button"
              data-testid={`floor-map-equipment-${dot.tag_id}`}
              title={`${dot.label} · ${status.label}`}
              aria-label={`${dot.label} · ${status.label}`}
              className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full ring-1 ring-background ${status.className}`}
              style={{ left: `${x}%`, top: `${y}%`, width: 9, height: 9 }}
              onClick={(event) => {
                event.stopPropagation();
                onEquipmentClick?.(dot.tag_id);
              }}
            >
              {dot.badge}
            </button>
          );
        });
      })}
    </div>
  );
}
