import { useNavigate } from 'react-router';
import { cn } from '../ui/utils';
import { clearStoredAuthSession, LOGIN_PATH } from '../../lib/auth';

type AdminNavProps = {
  active: 'verification' | 'nfc-mapping' | 'devices' | 'floor-map' | 'ai-report' | 'mypage';
};

const TABS: { key: AdminNavProps['active']; label: string; path: string }[] = [
  { key: 'verification', label: '장비 사용 이력 조회', path: '/verification' },
  { key: 'nfc-mapping', label: 'NFC 매핑', path: '/admin/nfc-mapping' },
  { key: 'devices', label: '기기 상태', path: '/admin/devices' },
  { key: 'floor-map', label: '층별 지도', path: '/admin/floor-map' },
  { key: 'ai-report', label: 'AI 기반 레포트', path: '/admin/ai-report' },
  { key: 'mypage', label: '마이페이지', path: '/me' },
];

export default function AdminNav({ active }: AdminNavProps) {
  const navigate = useNavigate();

  const logout = () => {
    clearStoredAuthSession();
    navigate(LOGIN_PATH, { replace: true });
  };

  return (
    <>
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className={cn('app-nav-tab', active === tab.key && 'app-nav-tab--active')}
          onClick={() => navigate(tab.path)}
        >
          {tab.label}
        </button>
      ))}
      <button type="button" className="app-nav-tab app-nav-tab--logout" onClick={logout}>
        로그아웃
      </button>
    </>
  );
}
