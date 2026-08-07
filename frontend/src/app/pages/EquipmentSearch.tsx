import { useEffect, useMemo, useState } from 'react';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import AppShell from '../components/layout/AppShell';
import StaffNav from '../components/layout/StaffNav';
import FloorMapView, { type FloorMapPin, type FloorMapEquipmentDot } from '../components/FloorMapView';
import { FLOOR_MAPS, type FloorNumber } from '../lib/floorMaps';
import { API_BASE_URL } from '../lib/runtime';
import { buildAuthHeaders, getStoredAuthSession, LOGIN_PATH } from '../lib/auth';
import { useAuthGuard, useLogout } from '../lib/useAuthGuard';

type LiveLocationItem = {
  tag_id: string;
  equipment_name: string | null;
  equipment_type: string | null;
  serial_number: string | null;
  asset_status: string;
  current_holder_user_id: number | null;
  current_holder_name: string | null;
  reader_id: string | null;
  location: string | null;
  rssi: number | null;
  updated_at: number | null;
  is_stale: boolean;
  is_online: boolean;
  last_seen: number | null;
};

type LiveReaderItem = {
  reader_id: string;
  location: string;
  is_online: boolean;
  last_seen: number | null;
  floor: number | null;
  map_x: number | null;
  map_y: number | null;
};

type EquipmentViewItem = {
  id: string;
  name: string;
  type: string;
  location: string;
  readerId: string;
  updatedAt: number | null;
  isStale: boolean;
  isOnline: boolean;
  lastSeen: number | null;
  assetStatus: string;
  currentHolderUserId: number | null;
  currentHolderName: string | null;
};

function getOnlineDotClass(isOnline: boolean) {
  return isOnline ? 'h-2.5 w-2.5 rounded-full dot-ok' : 'h-2.5 w-2.5 rounded-full dot-warn';
}

function getOnlineLabel(isOnline: boolean) {
  return isOnline ? '감지 중' : '감지 안 됨';
}

function formatLastReceivedAt(epoch: number | null) {
  if (!epoch) return '-';
  return new Date(epoch * 1000).toLocaleString('ko-KR', { hour12: false });
}

function getAssetStatusColor(status: string) {
  switch (status) {
    case 'checked_out':
      return 'h-2.5 w-2.5 rounded-full dot-err';
    case 'maintenance':
      return 'h-2.5 w-2.5 rounded-full dot-warn';
    case 'inactive':
      return 'h-2.5 w-2.5 rounded-full solid-neutral';
    default:
      return 'h-2.5 w-2.5 rounded-full dot-ok';
  }
}

function getAssetStatusLabel(status: string) {
  switch (status) {
    case 'checked_out':
      return '대여 중';
    case 'maintenance':
      return '점검 중';
    case 'inactive':
      return '비활성';
    default:
      return '사용 가능';
  }
}

function getShortTagId(tagId: string) {
  const head = tagId.split(':')[0] ?? tagId;
  return head.split('-')[0] ?? head;
}

// 위치 미확인(오프라인) 태그의 표시용 라벨. 좌측 "장비 목록"에는 그대로 노출되어야 하지만,
// 우측 위치 패널 그리드·위치 필터 드롭다운에는 실제 위치가 아니므로 절대 새어 들어가면 안 된다.
const UNLOCATED_LABEL = '감지 안 됨';

export default function EquipmentSearch() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedType, setSelectedType] = useState('전체');
  const [selectedLocation, setSelectedLocation] = useState('전체');
  const [selectedEquipment, setSelectedEquipment] = useState<string | null>(null);
  // 직원이 가장 먼저 보고 싶은 건 "장비가 지금 어디 있나"라서 지도를 기본으로 연다.
  const [viewMode, setViewMode] = useState<'list' | 'map'>('map');
  const [selectedFloor, setSelectedFloor] = useState<FloorNumber>(1);
  const [availableOnly, setAvailableOnly] = useState(false);
  const isAuthorized = useAuthGuard(() => {
    try {
      const session = getStoredAuthSession();
      if (!session?.token || !session.user) return LOGIN_PATH;
      if (session.user.role === 'admin') return '/verification';
      if (session.user.role !== 'staff') return LOGIN_PATH;
      return null;
    } catch {
      return LOGIN_PATH;
    }
  });

  const [liveItems, setLiveItems] = useState<LiveLocationItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState('');
  const [readers, setReaders] = useState<LiveReaderItem[]>([]);

  const logout = useLogout();

  const equipment = useMemo<EquipmentViewItem[]>(() => {
    return liveItems.map((item) => ({
      id: item.tag_id,
      name: item.equipment_name?.trim() || item.tag_id,
      type: item.equipment_type?.trim() || '미분류',
      location: item.location ?? UNLOCATED_LABEL,
      readerId: item.reader_id ?? '-',
      updatedAt: item.updated_at,
      isStale: item.is_stale,
      isOnline: item.is_online,
      lastSeen: item.last_seen,
      assetStatus: item.asset_status,
      currentHolderUserId: item.current_holder_user_id,
      currentHolderName: item.current_holder_name,
    }));
  }, [liveItems]);

  const equipmentTypes = useMemo(() => {
    const set = new Set(equipment.map((e) => e.type));
    return ['전체', ...Array.from(set)];
  }, [equipment]);

  const readerLocations = useMemo(
    () =>
      Array.from(
        new Set(
          readers
            .map((reader) => reader.location)
            .filter((location) => location.length > 0 && location !== UNLOCATED_LABEL),
        ),
      ),
    [readers],
  );

  // 장비가 아직 하나도 위치하지 않은 활성 리더 구역도 필터·패널에 노출되도록 리더 로스터를 합친다.
  const locations = useMemo(() => {
    const set = new Set([
      ...equipment.map((e) => e.location).filter((location) => location !== UNLOCATED_LABEL),
      ...readerLocations,
    ]);
    return ['전체', ...Array.from(set)];
  }, [equipment, readerLocations]);

  const locationPanels = useMemo(() => locations.filter((loc) => loc !== '전체'), [locations]);

  // 검색어·종류·대여 여부 필터만 반영한 목록. 리더 위치 패널과 지도는 위치 필터와
  // 무관하게 항상 이 목록을 사용한다.
  const searchAndTypeFilteredEquipment = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return equipment.filter((item) => {
      const matchesSearch =
        q.length === 0 ||
        item.name.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q) ||
        item.location.toLowerCase().includes(q);

      const matchesType = selectedType === '전체' || item.type === selectedType;
      const matchesAvailability = !availableOnly || item.assetStatus === 'available';
      return matchesSearch && matchesType && matchesAvailability;
    });
  }, [equipment, searchQuery, selectedType, availableOnly]);

  const filteredEquipment = useMemo(() => {
    return searchAndTypeFilteredEquipment.filter(
      (item) => selectedLocation === '전체' || item.location === selectedLocation,
    );
  }, [searchAndTypeFilteredEquipment, selectedLocation]);

  // 지도 탭: 선택된 층에 좌표가 배치된 리더만 핀으로 그리고, 그 리더에 속한 장비를 점으로 흩뿌린다.
  const floorPins = useMemo<FloorMapPin[]>(
    () =>
      readers
        .filter((r) => r.floor === selectedFloor && r.map_x !== null && r.map_y !== null)
        .map((r) => ({
          reader_id: r.reader_id,
          label: r.location,
          map_x: r.map_x as number,
          map_y: r.map_y as number,
        })),
    [readers, selectedFloor],
  );

  const floorEquipmentDots = useMemo<FloorMapEquipmentDot[]>(() => {
    const pinReaderIds = new Set(floorPins.map((p) => p.reader_id));
    return searchAndTypeFilteredEquipment
      .filter((eq) => pinReaderIds.has(eq.readerId))
      .map((eq) => ({ tag_id: eq.id, reader_id: eq.readerId, label: eq.name, assetStatus: eq.assetStatus }));
  }, [floorPins, searchAndTypeFilteredEquipment]);

  useEffect(() => {
    if (!isAuthorized) return;
    let cancelled = false;

    const fetchLiveLocations = async () => {
      try {
        const session = getStoredAuthSession();
        if (!session?.token) {
          logout();
          return;
        }
        const response = await fetch(`${API_BASE_URL}/rtls/live`, {
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
          throw new Error(payload?.detail ?? '실시간 위치 데이터를 가져오지 못했습니다.');
        }

        if (cancelled) return;
        const serverItems = Array.isArray(payload.items) ? (payload.items as LiveLocationItem[]) : [];
        const serverReaders = Array.isArray(payload.readers) ? (payload.readers as LiveReaderItem[]) : [];
        setLiveItems(serverItems);
        setReaders(serverReaders);
        setFetchError('');
      } catch (err) {
        if (cancelled) return;
        setLiveItems([]);
        setReaders([]);
        if (err instanceof Error) setFetchError(err.message);
        else setFetchError('실시간 위치 조회 중 오류가 발생했습니다.');
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    fetchLiveLocations();
    // 의료진 화면은 실시간 위치가 핵심이므로 짧은 주기로 새 값을 다시 받아온다.
    const intervalId = window.setInterval(fetchLiveLocations, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [isAuthorized, logout]);

  useEffect(() => {
    if (!selectedEquipment) return;
    if (!equipment.some((item) => item.id === selectedEquipment)) {
      // 실시간 폴링으로 태그가 목록에서 완전히 사라졌을 때 선택을 해제한다 (외부 데이터 변화에 대한 정당한 반응).
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedEquipment(null);
    }
  }, [equipment, selectedEquipment]);

  const selectedItem = filteredEquipment.find((item) => item.id === selectedEquipment) ?? null;

  if (!isAuthorized) {
    return null;
  }

  return (
    <AppShell actions={<StaffNav active="equipment" />} contentClassName="pt-4 sm:pt-5">
      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="space-y-3 fade-rise">
          <div className="surface-panel p-5">
            <div className="panel-header">
              <div>
                <div className="panel-title">장비 위치 검색</div>
              </div>
            </div>
            <div className="space-y-3">
              <Input
                placeholder="태그 ID, 장비명, 위치 검색"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />

              <div className="space-y-2">
                <label className="text-sm font-medium">장비 유형</label>
                <Select value={selectedType} onValueChange={setSelectedType}>
                  <SelectTrigger>
                    <SelectValue placeholder="유형 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {equipmentTypes.map((type) => (
                      <SelectItem key={type} value={type}>
                        {type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">위치 필터</label>
                <Select value={selectedLocation} onValueChange={setSelectedLocation}>
                  <SelectTrigger>
                    <SelectValue placeholder="위치 선택" />
                  </SelectTrigger>
                  <SelectContent>
                    {locations.map((location) => (
                      <SelectItem key={location} value={location}>
                        {location}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  checked={availableOnly}
                  onChange={(event) => setAvailableOnly(event.target.checked)}
                />
                사용 가능 장비만 보기
              </label>

              {fetchError ? <div className="alert alert-error">{fetchError}</div> : null}
            </div>
          </div>

          <div className="surface-panel p-3">
            <div className="panel-header px-2 pt-2">
              <div>
                <div className="panel-title">장비 목록</div>
              </div>
              <Badge variant="outline">추적 중 {equipment.length}개</Badge>
            </div>
            <div className="max-h-[720px] space-y-2 overflow-y-auto px-2 pb-2">
              {isLoading ? (
                <div className="empty-state">실시간 데이터 로딩 중입니다.</div>
              ) : filteredEquipment.length === 0 ? (
                <div className="empty-state">표시할 실시간 태그가 없습니다.</div>
              ) : (
                filteredEquipment.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedEquipment(item.id)}
                    className={`w-full rounded-lg border p-4 text-left transition-all ${
                      selectedEquipment === item.id
                        ? 'border-foreground bg-secondary'
                        : 'border-border bg-card hover:bg-secondary'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-2">
                        <div>
                          <h3 className="text-[1rem] leading-5">{item.name}</h3>
                          <p className="text-sm text-muted-foreground" title={item.id}>
                            {getShortTagId(item.id)}
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                          <span>{item.location}</span>
                        </div>
                      </div>
                      <span className={getAssetStatusColor(item.assetStatus)} />
                    </div>

                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">{item.type}</Badge>
                        <Badge variant="outline">{getAssetStatusLabel(item.assetStatus)}</Badge>
                      </div>
                      <div className="text-right text-xs text-muted-foreground">
                        <div>추적: {getOnlineLabel(item.isOnline)}</div>
                        {!item.isOnline ? <div>마지막 수신: {formatLastReceivedAt(item.lastSeen)}</div> : null}
                      </div>
                    </div>
                    {item.currentHolderName ? (
                      <div className="mt-2 text-xs text-muted-foreground">사용자: {item.currentHolderName}</div>
                    ) : null}
                  </button>
                ))
              )}
            </div>
          </div>
        </section>

        <section className="space-y-4 fade-rise-delay">
          <div className="surface-panel p-5">
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className={viewMode === 'map' ? 'app-nav-tab app-nav-tab--active' : 'app-nav-tab'}
                  onClick={() => setViewMode('map')}
                >
                  지도
                </button>
                <button
                  type="button"
                  className={viewMode === 'list' ? 'app-nav-tab app-nav-tab--active' : 'app-nav-tab'}
                  onClick={() => setViewMode('list')}
                >
                  목록
                </button>
              </div>
              <Badge variant="outline">활성 수신 구역 {locationPanels.length}개</Badge>
            </div>

            {viewMode === 'map' ? (
              <div className="space-y-3">
                <div className="flex gap-2">
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
                {floorPins.length === 0 ? (
                  <div className="empty-state">이 층에는 아직 배치된 구역이 없습니다.</div>
                ) : (
                  <>
                    <FloorMapView
                      floor={selectedFloor}
                      pins={floorPins}
                      equipment={floorEquipmentDots}
                      onEquipmentClick={(tagId) => setSelectedEquipment(tagId)}
                    />
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full dot-ok" />
                        사용 가능
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full dot-err" />
                        대여 중
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full dot-warn" />
                        점검 중
                      </span>
                      <span className="ml-auto">이미지 출처: 순천향대학교 천안병원</span>
                    </div>
                  </>
                )}
              </div>
            ) : locationPanels.length === 0 ? (
              <div className="empty-state">아직 수신된 RTLS 위치 데이터가 없습니다.</div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
                {locationPanels.map((location) => {
                  const roomItems = searchAndTypeFilteredEquipment.filter((eq) => eq.location === location);
                  const readerForLocation = readers.find((r) => r.location === location);
                  return (
                    <section key={location} className="rounded-lg border border-border bg-card p-4">
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-[1.02rem]">{location}</h3>
                            {readerForLocation ? (
                              <span className={getOnlineDotClass(readerForLocation.is_online)} />
                            ) : null}
                          </div>
                          <p className="mt-1 text-sm text-muted-foreground">{roomItems.length}개 장비 수신</p>
                        </div>
                        <Badge variant="outline">{location}</Badge>
                      </div>
                      <div className="space-y-2">
                        {roomItems.length === 0 ? (
                          <div className="rounded-lg border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground">
                            현재 태그 없음
                          </div>
                        ) : (
                          roomItems.map((eq) => (
                            <button
                              key={eq.id}
                              type="button"
                              onClick={() => setSelectedEquipment(eq.id)}
                              className={`flex w-full items-center justify-between gap-3 rounded-lg border px-4 py-3 text-left transition-all ${
                                selectedEquipment === eq.id
                                  ? 'border-foreground bg-secondary'
                                  : 'border-border bg-card hover:bg-secondary'
                              }`}
                            >
                              <div className="min-w-0">
                                <div className="truncate font-medium text-foreground">{eq.name}</div>
                                <div className="mt-1 text-xs text-muted-foreground" title={eq.id}>
                                  {getShortTagId(eq.id)}
                                </div>
                              </div>
                              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                <span className={getAssetStatusColor(eq.assetStatus)} />
                                <span className="whitespace-nowrap">{getAssetStatusLabel(eq.assetStatus)}</span>
                              </div>
                            </button>
                          ))
                        )}
                      </div>
                    </section>
                  );
                })}
              </div>
            )}
          </div>

          <div className="surface-panel p-5">
            <div className="panel-header">
              <div>
                <div className="panel-title">선택 장비 상세</div>
              </div>
              {selectedItem ? <Badge>{selectedItem.name}</Badge> : <Badge variant="outline">선택 없음</Badge>}
            </div>

            {!selectedItem ? (
              <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center text-muted-foreground">
                좌측 목록 또는 위치 패널에서 장비를 선택해 주세요.
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-lg border border-border bg-card p-5">
                  <div className="metric-label">장비명</div>
                  <div className="mt-3 text-xl font-semibold tracking-[-0.04em]">{selectedItem.name}</div>
                </div>
                <div className="rounded-lg border border-border bg-card p-5">
                  <div className="metric-label">현재 위치</div>
                  <div className="mt-3 text-xl font-semibold tracking-[-0.04em]">{selectedItem.location}</div>
                </div>
                <div className="rounded-lg border border-border bg-card p-5">
                  <div className="metric-label">리더 ID</div>
                  <div className="mt-3 text-xl font-semibold tracking-[-0.04em]">{selectedItem.readerId}</div>
                </div>
                <div className="rounded-lg border border-border bg-card p-5">
                  <div className="metric-label">업데이트 상태</div>
                  <div className="mt-3">
                    <div className="flex items-center gap-3 text-lg font-semibold tracking-[-0.04em]">
                      <span className={getOnlineDotClass(selectedItem.isOnline)} />
                      {getOnlineLabel(selectedItem.isOnline)}
                    </div>
                    <div className="mt-2 text-sm text-muted-foreground">
                      마지막 수신 시각: {formatLastReceivedAt(selectedItem.lastSeen)}
                    </div>
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card p-5">
                  <div className="metric-label">사용 상태</div>
                  <div className="mt-3 flex items-center gap-3 text-xl font-semibold tracking-[-0.04em]">
                    <span className={getAssetStatusColor(selectedItem.assetStatus)} />
                    {getAssetStatusLabel(selectedItem.assetStatus)}
                  </div>
                </div>
                <div className="rounded-lg border border-border bg-card p-5">
                  <div className="metric-label">현재 사용자</div>
                  <div className="mt-3 text-xl font-semibold tracking-[-0.04em]">
                    {selectedItem.currentHolderName ?? '-'}
                  </div>
                </div>
              </div>
            )}

            {selectedItem ? (
              <div className="mt-4 inline-meta">
                <span className="inline-meta__item" title={selectedItem.id}>
                  Tag {getShortTagId(selectedItem.id)}
                </span>
                <span className="inline-meta__item">{selectedItem.type}</span>
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </AppShell>
  );
}
