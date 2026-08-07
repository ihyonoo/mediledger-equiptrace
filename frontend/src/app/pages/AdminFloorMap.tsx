import { useCallback, useState } from 'react';
import AppShell from '../components/layout/AppShell';
import AdminNav from '../components/layout/AdminNav';
import { Button } from '../components/ui/button';
import ProvenanceDot from '../components/ui/ProvenanceDot';
import FloorMapView, { type FloorMapPin } from '../components/FloorMapView';
import { FLOOR_MAPS, type FloorNumber } from '../lib/floorMaps';
import { API_BASE_URL } from '../lib/runtime';
import { buildAuthHeaders, getStoredAuthSession, LOGIN_PATH } from '../lib/auth';
import { useAuthGuard, useLogout, useRunWhenReady } from '../lib/useAuthGuard';

type AdminReaderRow = {
  reader_id: string;
  location_name: string | null;
  floor: number | null;
  map_x: number | null;
  map_y: number | null;
  is_active: boolean;
  is_real_hardware: boolean;
  last_seen_at: string | null;
};

export default function AdminFloorMap() {
  const isAuthorized = useAuthGuard(() => {
    try {
      const session = getStoredAuthSession();
      if (!session?.token || !session.user) return LOGIN_PATH;
      if (session.user.role !== 'admin') return '/equipment';
      return null;
    } catch {
      return LOGIN_PATH;
    }
  });
  const logout = useLogout();

  const [readers, setReaders] = useState<AdminReaderRow[]>([]);
  const [selectedFloor, setSelectedFloor] = useState<FloorNumber>(1);
  const [pendingReaderId, setPendingReaderId] = useState<string | null>(null);
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [hideSimulated, setHideSimulated] = useState(false);

  const fetchReaders = useCallback(async () => {
    const session = getStoredAuthSession();
    if (!session?.token) {
      logout();
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/admin/readers`, {
        method: 'GET',
        cache: 'no-store',
        headers: buildAuthHeaders(session.token),
      });
      const payload = await response.json().catch(() => null);
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
      if (!response.ok || !payload?.ok) {
        throw new Error(payload?.detail ?? '리더 목록을 가져오지 못했습니다.');
      }
      setReaders(Array.isArray(payload.items) ? payload.items : []);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '리더 목록 조회 중 오류가 발생했습니다.');
    }
  }, [logout]);

  useRunWhenReady(isAuthorized, fetchReaders);

  const visibleReaders = hideSimulated ? readers.filter((r) => r.is_real_hardware) : readers;
  const unplacedReaders = visibleReaders.filter((r) => r.map_x === null || r.map_y === null);
  const placedOnFloor = visibleReaders.filter((r) => r.floor === selectedFloor && r.map_x !== null && r.map_y !== null);

  const updateLocalPosition = (readerId: string, floor: FloorNumber, mapX: number, mapY: number) => {
    setReaders((prev) => prev.map((r) => (r.reader_id === readerId ? { ...r, floor, map_x: mapX, map_y: mapY } : r)));
    setDirtyIds((prev) => new Set(prev).add(readerId));
  };

  const handlePendingPlace = (mapX: number, mapY: number) => {
    if (!pendingReaderId) return;
    updateLocalPosition(pendingReaderId, selectedFloor, mapX, mapY);
    setPendingReaderId(null);
  };

  const handlePinMoved = (readerId: string, mapX: number, mapY: number) => {
    updateLocalPosition(readerId, selectedFloor, mapX, mapY);
  };

  const handleSave = async () => {
    const session = getStoredAuthSession();
    if (!session?.token) {
      logout();
      return;
    }
    setSaving(true);
    setError('');
    const failed: string[] = [];
    for (const readerId of dirtyIds) {
      const reader = readers.find((r) => r.reader_id === readerId);
      if (!reader || reader.floor === null || reader.map_x === null || reader.map_y === null) continue;
      try {
        const response = await fetch(`${API_BASE_URL}/admin/readers/${readerId}/map-position`, {
          method: 'PUT',
          headers: buildAuthHeaders(session.token, { 'Content-Type': 'application/json' }),
          body: JSON.stringify({ floor: reader.floor, map_x: reader.map_x, map_y: reader.map_y }),
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) throw new Error();
      } catch {
        failed.push(readerId);
      }
    }
    setDirtyIds(new Set(failed));
    if (failed.length > 0) {
      setError(`${failed.length}개 리더 좌표 저장에 실패했습니다.`);
    }
    setSaving(false);
  };

  if (!isAuthorized) return null;

  const pins: FloorMapPin[] = placedOnFloor.map((r) => ({
    reader_id: r.reader_id,
    label: r.location_name ?? r.reader_id,
    map_x: r.map_x as number,
    map_y: r.map_y as number,
    badge: <ProvenanceDot isRealHardware={r.is_real_hardware} />,
  }));

  return (
    <AppShell wide actions={<AdminNav active="floor-map" />} contentClassName="pt-4 sm:pt-5">
      <div className="space-y-4">
        <section className="surface-panel p-5 fade-rise">
          <div className="panel-header">
            <div className="panel-title">층별 평면도 핀 편집기</div>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  checked={hideSimulated}
                  onChange={(event) => setHideSimulated(event.target.checked)}
                />
                모의 데이터 숨기기
              </label>
              <Button type="button" disabled={dirtyIds.size === 0 || saving} onClick={handleSave}>
                {saving ? '저장 중...' : `변경사항 저장${dirtyIds.size > 0 ? ` (${dirtyIds.size})` : ''}`}
              </Button>
            </div>
          </div>
          {error ? <div className="alert alert-error mb-3">{error}</div> : null}
          <div className="mb-4 flex gap-2">
            {FLOOR_MAPS.map((f) => (
              <button
                key={f.floor}
                type="button"
                className={f.floor === selectedFloor ? 'app-nav-tab app-nav-tab--active' : 'app-nav-tab'}
                onClick={() => setSelectedFloor(f.floor)}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="grid gap-4 md:grid-cols-[240px_1fr]">
            <div className="space-y-2">
              <div className="metric-label">미배치 리더</div>
              {unplacedReaders.length === 0 ? (
                <div className="empty-state">모든 리더가 배치되었습니다.</div>
              ) : (
                unplacedReaders.map((r) => (
                  <button
                    key={r.reader_id}
                    type="button"
                    className={
                      pendingReaderId === r.reader_id
                        ? 'w-full rounded-lg border-2 border-primary bg-card px-3 py-2 text-left text-sm'
                        : 'w-full rounded-lg border border-border bg-card px-3 py-2 text-left text-sm'
                    }
                    onClick={() => setPendingReaderId(r.reader_id)}
                  >
                    <span className="inline-flex items-center gap-1.5">
                      {r.location_name ?? r.reader_id}
                      <ProvenanceDot isRealHardware={r.is_real_hardware} />
                    </span>
                  </button>
                ))
              )}
            </div>
            <FloorMapView
              floor={selectedFloor}
              pins={pins}
              // 좌표를 배치·이동하는 화면이므로 여기서는 구역 표식을 보여준다.
              showPins
              pendingReaderId={pendingReaderId}
              onPendingPlace={handlePendingPlace}
              onPinMoved={handlePinMoved}
            />
          </div>
        </section>
      </div>
    </AppShell>
  );
}
