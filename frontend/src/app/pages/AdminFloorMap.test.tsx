import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router';
import AdminFloorMap from './AdminFloorMap';
import { LOGIN_PATH } from '../lib/auth';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/admin/floor-map']}>
      <Routes>
        <Route path="/admin/floor-map" element={<AdminFloorMap />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

function storeSession(role: 'admin' | 'staff') {
  sessionStorage.setItem(
    'auth_session',
    JSON.stringify({
      token: 'test-token',
      expires_at: 9999999999,
      user: { user_id: 1, username: 'u', display_name: 'u', role },
    }),
  );
}

const UNPLACED_READER = {
  reader_id: 'M101',
  location_name: '1층 병동 A',
  floor: null,
  map_x: null,
  map_y: null,
  is_active: true,
  is_real_hardware: false,
  last_seen_at: null,
};

const PLACED_REAL_READER = {
  reader_id: 'M502',
  location_name: '영상의학과',
  floor: 1,
  map_x: 60,
  map_y: 40,
  is_active: true,
  is_real_hardware: true,
  last_seen_at: null,
};

const PLACED_SIM_READER = {
  reader_id: 'M105',
  location_name: '1층 영상센터 X-ray실',
  floor: 1,
  map_x: 70,
  map_y: 45,
  is_active: true,
  is_real_hardware: false,
  last_seen_at: null,
};

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

describe('AdminFloorMap auth guard', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('redirects to LOGIN_PATH when there is no session', () => {
    renderPage();
    expect(screen.getByTestId('location')).toHaveTextContent(LOGIN_PATH);
  });

  it('redirects staff users to /equipment', () => {
    storeSession('staff');
    renderPage();
    expect(screen.getByTestId('location')).toHaveTextContent('/equipment');
  });
});

describe('AdminFloorMap pin placement', () => {
  beforeEach(() => {
    sessionStorage.clear();
    storeSession('admin');
    mockContainerRect();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('loads readers and lists unplaced ones in the sidebar', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ ok: true, count: 1, items: [UNPLACED_READER] }),
      }),
    );

    renderPage();

    expect(await screen.findByText('1층 병동 A')).toBeInTheDocument();
  });

  it('places a pending reader on map click and marks it unsaved, then saves via PUT', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            item: {
              reader_id: 'M101',
              location_name: '1층 병동 A',
              floor: 1,
              map_x: 25,
              map_y: 50,
              is_real_hardware: false,
            },
          }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, count: 1, items: [UNPLACED_READER] }),
      };
    });
    vi.stubGlobal('fetch', fetchMock);

    renderPage();

    const sidebarEntry = await screen.findByText('1층 병동 A');
    fireEvent.click(sidebarEntry);

    const mapContainer = screen.getByTestId('floor-map-container');
    fireEvent.click(mapContainer, { clientX: 250, clientY: 500 });

    expect(screen.getByTestId('floor-map-pin-M101')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /저장/ })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /저장/ }));

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === 'PUT');
      expect(putCall).toBeTruthy();
    });
    const [putUrl, putInit] = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === 'PUT')!;
    expect(putUrl).toContain('/admin/readers/M101/map-position');
    expect(JSON.parse((putInit as RequestInit).body as string)).toEqual({ floor: 1, map_x: 25, map_y: 50 });
  });
});

describe('AdminFloorMap simulated data toggle', () => {
  beforeEach(() => {
    sessionStorage.clear();
    storeSession('admin');
    mockContainerRect();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('hides simulated readers from the sidebar and the map when toggled on', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ ok: true, count: 3, items: [UNPLACED_READER, PLACED_REAL_READER, PLACED_SIM_READER] }),
      }),
    );

    renderPage();

    await screen.findByText('1층 병동 A');
    expect(screen.getByTestId('floor-map-pin-M502')).toBeInTheDocument();
    expect(screen.getByTestId('floor-map-pin-M105')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: '모의 데이터 숨기기' }));

    expect(screen.queryByText('1층 병동 A')).not.toBeInTheDocument();
    expect(screen.queryByTestId('floor-map-pin-M105')).not.toBeInTheDocument();
    expect(screen.getByTestId('floor-map-pin-M502')).toBeInTheDocument();
  });
});
