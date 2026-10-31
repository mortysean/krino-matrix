// The KRINO trademark: two isometric 2×2 grids of rhombi sharing the dark centre cell, the lower grid's bottom
// cell split in two shades, on a vertical axis that ends in a dot at each side. Cell shades are CSS variables, so
// the dark theme gets the negative version; gaps are strokes in the page colour.

const A = 12          // half-width of a cell
const B = 5           // half-height of a cell
const DROP = 1.2      // the lower grid sits this much below the upper one

function cell(cx: number, cy: number) {
  return `M${cx - A} ${cy}L${cx} ${cy - B}L${cx + A} ${cy}L${cx} ${cy + B}Z`
}

const LOW = B + DROP

export function Mark({ size = 26, spinning = false }: { size?: number; spinning?: boolean }) {
  return (
    <svg className={`mark ${spinning ? 'spinning' : ''}`} width={size * 52 / 62} height={size} viewBox="-26 -31 52 62"
      aria-hidden="true">
      <g className="axis">
        <path d="M0 -26.5V-15" className="dash" />
        <path d="M0 -15V-5" className="solid" />
        <path d={`M0 ${2 * B + LOW}V25`} className="dash" />
        <circle className="dot top" cx="0" cy="-27.5" r="2.6" />
        <circle className="dot bottom" cx="0" cy="26" r="2.6" />
      </g>
      <g className="cells">
        <g className="upper">
          <path d={cell(0, -2 * B)} className="c c4" style={{ '--n': 0 } as React.CSSProperties} />
          <path d={cell(-A, -B)} className="c c3" style={{ '--n': 1 } as React.CSSProperties} />
          <path d={cell(A, -B)} className="c c3" style={{ '--n': 2 } as React.CSSProperties} />
          <path d={cell(0, 0)} className="c c1" style={{ '--n': 3 } as React.CSSProperties} />
        </g>
        <g className="lower">
          <path d={cell(-A, LOW)} className="c c1" style={{ '--n': 4 } as React.CSSProperties} />
          <path d={cell(A, LOW)} className="c c4" style={{ '--n': 5 } as React.CSSProperties} />
          <path d={`M${-A} ${B + LOW}L0 ${LOW}L0 ${2 * B + LOW}Z`} className="c c2" style={{ '--n': 6 } as React.CSSProperties} />
          <path d={`M0 ${LOW}L${A} ${B + LOW}L0 ${2 * B + LOW}Z`} className="c c2b" style={{ '--n': 7 } as React.CSSProperties} />
        </g>
      </g>
    </svg>
  )
}

export function Logo({ size = 30 }: { size?: number }) {
  return (
    <span className="logo" aria-label="KRINO MATRIX">
      <Mark size={size} />
      <span className="word" aria-hidden="true"><b>KRINO</b><span>MATRIX</span></span>
    </span>
  )
}
