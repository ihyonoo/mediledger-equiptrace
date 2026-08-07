// 관리자 화면에서만 실물/모의(시뮬레이션) 데이터를 아주 작은 점으로 구분한다.
// 텍스트 라벨은 절대 두지 않는다 — 방/장비 이름 자체는 시연 중 진짜처럼 보여야 하므로,
// 이 점은 hover 툴팁으로만 의미를 설명한다.

type ProvenanceDotProps = {
  isRealHardware: boolean;
};

export default function ProvenanceDot({ isRealHardware }: ProvenanceDotProps) {
  if (isRealHardware) return null;

  return (
    <span
      data-testid="provenance-dot"
      title="모의 데이터"
      className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/40"
    />
  );
}
