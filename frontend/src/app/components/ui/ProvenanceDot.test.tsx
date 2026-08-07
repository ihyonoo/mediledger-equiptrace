import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProvenanceDot from './ProvenanceDot';

describe('ProvenanceDot', () => {
  it('renders nothing for real hardware', () => {
    render(<ProvenanceDot isRealHardware />);
    expect(screen.queryByTestId('provenance-dot')).not.toBeInTheDocument();
  });

  it('renders a titled dot for simulated data, with no visible text label', () => {
    render(<ProvenanceDot isRealHardware={false} />);
    const dot = screen.getByTestId('provenance-dot');
    expect(dot).toHaveAttribute('title', '모의 데이터');
    expect(dot).toHaveTextContent('');
  });
});
