import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router';
import EquipmentSearch from './EquipmentSearch';

function storeStaffSession() {
  sessionStorage.setItem(
    'auth_session',
    JSON.stringify({
      token: 'test-token',
      expires_at: 9999999999,
      user: { user_id: 1, username: 'u', display_name: 'u', role: 'staff' },
    }),
  );
}

function mockContainerRect() {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 1000,
    bottom: 1000,
    width: 1000,
    height: 1000,
    toJSON: () => {},
  });
}

const LIVE_PAYLOAD = {
  ok: true,
  count: 2,
  ts: 0,
  items: [
    {
      tag_id: 'EQ-0001',
      equipment_name: '수액펌프 1호',
      equipment_type: '수액펌프',
      serial_number: 'BME-2024-00001',
      asset_status: 'available',
      current_holder_user_id: null,
      current_holder_name: null,
      reader_id: 'M101',
      location: '1층 병동 A',
      rssi: -55,
      updated_at: 0,
      is_stale: false,
      is_online: true,
      last_seen: 0,
    },
    {
      tag_id: 'EQ-0002',
      equipment_name: '수액펌프 2호',
      equipment_type: '수액펌프',
      serial_number: 'BME-2024-00002',
      asset_status: 'checked_out',
      current_holder_user_id: 7,
      current_holder_name: '박수현',
      reader_id: 'M101',
      location: '1층 병동 A',
      rssi: -58,
      updated_at: 0,
      is_stale: false,
      is_online: true,
      last_seen: 0,
    },
  ],
  readers: [
    { reader_id: 'M101', location: '1층 병동 A', is_online: true, last_seen: 0, floor: 1, map_x: 25, map_y: 50 },
  ],
  readers_online: 1,
  readers_total: 1,
  tags_online: 1,
  tags_total: 1,
};

describe('EquipmentSearch map view', () => {
  beforeEach(() => {
    sessionStorage.clear();
    storeStaffSession();
    mockContainerRect();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => LIVE_PAYLOAD,
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('opens on the map view without needing to switch tabs', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('floor-map-container')).toBeInTheDocument();
    expect(await screen.findByTestId('floor-map-equipment-EQ-0001')).toBeInTheDocument();
  });

  it('shows the equipment dot without drawing a zone marker', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('floor-map-equipment-EQ-0001')).toBeInTheDocument();
    // 직원 지도에는 구역 표식을 그리지 않는다 — 평면도에 이미 구역명이 인쇄돼 있다.
    expect(screen.queryByTestId('floor-map-pin-M101')).not.toBeInTheDocument();
  });

  it('colors the equipment dot by its asset status on the map', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId('floor-map-equipment-EQ-0001')).toHaveClass('dot-ok');
    expect(screen.getByTestId('floor-map-equipment-EQ-0002')).toHaveClass('dot-err');
  });

  it('hides checked-out equipment from the map when the available-only filter is on', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByTestId('floor-map-equipment-EQ-0002');
    fireEvent.click(screen.getByRole('checkbox', { name: '사용 가능 장비만 보기' }));

    expect(screen.queryByTestId('floor-map-equipment-EQ-0002')).not.toBeInTheDocument();
    expect(screen.getByTestId('floor-map-equipment-EQ-0001')).toBeInTheDocument();
  });

  it('hides checked-out equipment from the list too when the available-only filter is on', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findAllByText('수액펌프 2호');
    fireEvent.click(screen.getByRole('checkbox', { name: '사용 가능 장비만 보기' }));

    expect(screen.queryByText('수액펌프 2호')).not.toBeInTheDocument();
    expect(screen.getAllByText('수액펌프 1호').length).toBeGreaterThan(0);
  });

  it('no longer shows the reader panel heading', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByTestId('floor-map-container');
    expect(screen.queryByText('리더 위치 패널')).not.toBeInTheDocument();
  });

  it('selects the equipment detail panel when its map dot is clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/equipment']}>
        <Routes>
          <Route path="/equipment" element={<EquipmentSearch />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findAllByText('수액펌프 1호');
    fireEvent.click(screen.getByRole('button', { name: '지도' }));
    const dot = await screen.findByTestId('floor-map-equipment-EQ-0001');
    fireEvent.click(dot);

    await waitFor(() => {
      expect(screen.getByText('선택 장비 상세').closest('div.surface-panel')).toHaveTextContent('수액펌프 1호');
    });
  });
});
