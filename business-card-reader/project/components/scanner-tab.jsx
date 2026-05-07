// Scanner Tab Component
const { useState, useEffect, useRef, useCallback } = React;

// ─── Mock data ────────────────────────────────────────────────────────────────
const MOCK_RESULTS = [
  {
    id: 1, filename: 'marco_ribeiro.vcf', locked: false,
    source: 'business_cards_batch1.jpg',
    via: 'GLM-OCR', time: 1.3,
    contact: {
      fullName: 'Marco Ribeiro', title: 'Head of Engineering',
      company: 'Steinweg Brokers', email: 'marco.ribeiro@steinweg.com',
      phone: '+55 11 9 8765-4321', mobile: '+55 11 9 8765-4321',
      website: 'steinweg.com', linkedin: 'linkedin.com/in/marcoribeiro',
      address: 'Av. Paulista, 1234 — São Paulo, SP'
    }
  },
  {
    id: 2, filename: 'ana_costa.vcf', locked: true,
    source: 'business_cards_batch1.jpg',
    via: 'QR Code', time: 0.1,
    contact: {
      fullName: 'Ana Costa', title: 'Director of Sales',
      company: 'Nexus Capital', email: 'ana.costa@nexuscap.com',
      phone: '+55 21 3200-0000', mobile: '+55 21 98800-1234',
      website: 'nexuscapital.com.br', linkedin: '',
      address: 'Rua da Quitanda, 86 — Rio de Janeiro, RJ'
    }
  },
  {
    id: 3, filename: 'pierre_dupont.vcf', locked: false,
    source: 'card_scan_2.png',
    via: 'GLM-OCR', time: 1.8,
    contact: {
      fullName: 'Pierre Dupont', title: 'Investment Manager',
      company: 'Société Générale', email: 'p.dupont@socgen.fr',
      phone: '+33 1 42 14 20 00', mobile: '',
      website: 'societegenerale.com', linkedin: 'linkedin.com/in/pierredupont',
      address: '29 Boulevard Haussmann, Paris, France'
    }
  },
  {
    id: 4, filename: 'yuki_tanaka.vcf', locked: false,
    source: 'card_scan_2.png',
    via: 'GLM-OCR', time: 2.1,
    contact: {
      fullName: 'Yuki Tanaka', title: 'Chief Technology Officer',
      company: 'Fujitsu Corp.', email: 'y.tanaka@fujitsu.com',
      phone: '+81 3 6252-2220', mobile: '',
      website: 'fujitsu.com', linkedin: '',
      address: 'Shibuya-ku, Tokyo, Japan'
    }
  },
];

// ─── Shared UI Atoms ──────────────────────────────────────────────────────────
function Btn({ variant = 'secondary', size = 'md', icon: Icon, children, onClick, disabled, style = {} }) {
  const base = {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    border: 'none', borderRadius: 'var(--radius-sm)', cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit', fontWeight: 500, transition: 'all 0.15s ease',
    opacity: disabled ? 0.45 : 1, whiteSpace: 'nowrap',
  };
  const sizes = { sm: { padding: '5px 10px', fontSize: 12 }, md: { padding: '7px 14px', fontSize: 13 }, lg: { padding: '10px 18px', fontSize: 14 } };
  const variants = {
    primary: { background: 'var(--accent)', color: 'white' },
    secondary: { background: 'var(--surface)', color: 'var(--text-primary)', border: '1px solid var(--border)' },
    ghost: { background: 'transparent', color: 'var(--text-secondary)', border: '1px solid transparent' },
    danger: { background: 'var(--danger-soft)', color: 'var(--danger)', border: '1px solid oklch(85% 0.05 25)' },
    success: { background: 'var(--success-soft)', color: 'var(--success)', border: '1px solid oklch(85% 0.05 145)' },
  };
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={disabled ? undefined : onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ ...base, ...sizes[size], ...variants[variant], filter: hovered && !disabled ? 'brightness(0.92)' : 'none', ...style }}
    >
      {Icon && <Icon width={13} height={13} color="currentColor" />}
      {children}
    </button>
  );
}

function Badge({ label, color = 'neutral', dot = false }) {
  const colors = {
    neutral: { bg: 'var(--bg)', text: 'var(--text-secondary)', border: 'var(--border)' },
    blue: { bg: 'var(--accent-soft)', text: 'var(--accent)', border: 'oklch(85% 0.08 264)' },
    green: { bg: 'var(--success-soft)', text: 'var(--success)', border: 'oklch(85% 0.06 145)' },
    amber: { bg: 'var(--warning-soft)', text: 'var(--warning)', border: 'oklch(88% 0.06 60)' },
    red: { bg: 'var(--danger-soft)', text: 'var(--danger)', border: 'oklch(88% 0.06 25)' },
  };
  const c = colors[color] || colors.neutral;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 7px', borderRadius: 99, fontSize: 11, fontWeight: 500,
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
    }}>
      {dot && <span style={{ width: 5, height: 5, borderRadius: '50%', background: c.text }} />}
      {label}
    </span>
  );
}

function Spinner({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" style={{ animation: 'spin 0.75s linear infinite', flexShrink: 0 }}>
      <circle cx="8" cy="8" r="6" fill="none" stroke="var(--border-strong)" strokeWidth="2" />
      <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function Divider({ style = {} }) {
  return <div style={{ height: 1, background: 'var(--border)', ...style }} />;
}

// ─── Upload Zone ──────────────────────────────────────────────────────────────
function UploadZone({ onFilesAdded }) {
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef();

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files).filter(f =>
      f.type.startsWith('image/') || f.name.endsWith('.pdf')
    );
    if (files.length) onFilesAdded(files);
  }, [onFilesAdded]);

  const handleChange = (e) => {
    const files = Array.from(e.target.files);
    if (files.length) onFilesAdded(files);
  };

  return (
    <div
      onClick={() => fileRef.current.click()}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      style={{
        border: `1.5px dashed ${dragging ? 'var(--accent)' : 'var(--border-strong)'}`,
        borderRadius: 'var(--radius-lg)',
        background: dragging ? 'var(--accent-soft)' : 'var(--surface)',
        padding: '36px 24px',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12,
        cursor: 'pointer', transition: 'all 0.2s ease',
        textAlign: 'center',
      }}
    >
      <div style={{
        width: 44, height: 44, borderRadius: 12,
        background: dragging ? 'var(--accent)' : 'var(--bg)',
        border: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'all 0.2s',
      }}>
        <Icons.upload color={dragging ? 'white' : 'var(--text-secondary)'} width={20} height={20} />
      </div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-primary)', marginBottom: 4 }}>
          Drop card images here
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>
          PNG, JPG, PDF — single or batch scans
        </div>
      </div>
      <input ref={fileRef} type="file" multiple accept="image/*,.pdf" onChange={handleChange} style={{ display: 'none' }} />
    </div>
  );
}

// ─── Config Panel ─────────────────────────────────────────────────────────────
function ConfigPanel({ config, onChange }) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-primary)', fontFamily: 'inherit', fontSize: 13, fontWeight: 500,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icons.settings color="var(--text-secondary)" width={15} height={15} />
          Processing Settings
        </div>
        <Icons.chevronDown color="var(--text-tertiary)" style={{ transform: open ? 'rotate(0deg)' : 'rotate(-90deg)', transition: 'transform 0.2s' }} />
      </button>

      {open && (
        <div style={{ padding: '0 16px 16px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Divider style={{ marginBottom: 2 }} />

          {/* Vision Model */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>Vision Model</label>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {['glm-ocr', 'llama3.2-vision', 'llava:13b', 'claude-3'].map(m => (
                <button key={m}
                  onClick={() => onChange({ ...config, model: m })}
                  style={{
                    padding: '5px 10px', borderRadius: 99, fontSize: 12, border: '1px solid',
                    borderColor: config.model === m ? 'var(--accent)' : 'var(--border)',
                    background: config.model === m ? 'var(--accent-soft)' : 'var(--bg)',
                    color: config.model === m ? 'var(--accent)' : 'var(--text-secondary)',
                    fontFamily: 'inherit', cursor: 'pointer', fontWeight: config.model === m ? 500 : 400,
                    transition: 'all 0.15s',
                  }}
                >
                  {m === 'glm-ocr' && <Icons.bolt color="currentColor" width={10} height={10} style={{ marginRight: 3, display: 'inline' }} />}
                  {m}
                </button>
              ))}
            </div>
            {config.model === 'glm-ocr' && (
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--success)', display: 'flex', alignItems: 'center', gap: 4 }}>
                <Icons.bolt color="currentColor" width={10} height={10} />
                0.9B params — fastest, #1 OCR benchmark
              </div>
            )}
          </div>

          {/* Detection Mode */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>Detection Mode</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
              {[
                { id: 'auto', label: 'Automatic', desc: 'Edge detection' },
                { id: 'single', label: 'Single Card', desc: 'Full image' },
                { id: 'grid', label: 'Grid Layout', desc: 'Rows × cols' },
              ].map(({ id, label, desc }) => (
                <button key={id}
                  onClick={() => onChange({ ...config, mode: id })}
                  style={{
                    padding: '8px 10px', borderRadius: 6, border: '1px solid',
                    borderColor: config.mode === id ? 'var(--accent)' : 'var(--border)',
                    background: config.mode === id ? 'var(--accent-soft)' : 'var(--bg)',
                    cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit', transition: 'all 0.15s',
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 500, color: config.mode === id ? 'var(--accent)' : 'var(--text-primary)' }}>{label}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Grid controls */}
          {config.mode === 'grid' && (
            <div style={{ display: 'flex', gap: 12 }}>
              {[['rows', 'Rows', config.rows], ['cols', 'Columns', config.cols]].map(([key, lbl, val]) => (
                <div key={key} style={{ flex: 1 }}>
                  <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>{lbl}</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button onClick={() => onChange({ ...config, [key]: Math.max(1, val - 1) })}
                      style={{ width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', cursor: 'pointer', fontSize: 16, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>−</button>
                    <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', minWidth: 20, textAlign: 'center' }}>{val}</span>
                    <button onClick={() => onChange({ ...config, [key]: Math.min(8, val + 1) })}
                      style={{ width: 28, height: 28, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', cursor: 'pointer', fontSize: 16, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>+</button>
                  </div>
                </div>
              ))}
              <div style={{ alignSelf: 'flex-end', paddingBottom: 4, fontSize: 13, color: 'var(--text-tertiary)' }}>
                = {config.rows * config.cols} cards
              </div>
            </div>
          )}

          {/* Timeout */}
          <div>
            <label style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: 6 }}>
              Timeout — <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{config.timeout}s</span>
            </label>
            <input type="range" min={60} max={600} step={30} value={config.timeout}
              onChange={e => onChange({ ...config, timeout: +e.target.value })}
              style={{ width: '100%', accentColor: 'var(--accent)' }} />
          </div>
        </div>
      )}
    </div>
  );
}

// ─── File Queue ───────────────────────────────────────────────────────────────
function FileQueue({ files, onRemove }) {
  if (!files.length) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {files.map((f, i) => (
        <div key={i} style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '8px 12px', background: 'var(--surface)',
          border: '1px solid var(--border)', borderRadius: 6,
        }}>
          <div style={{ width: 30, height: 30, borderRadius: 5, background: 'var(--bg)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Icons.card color="var(--text-tertiary)" width={14} height={14} />
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</div>
            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{(f.size / 1024).toFixed(0)} KB</div>
          </div>
          <button onClick={() => onRemove(i)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 4, borderRadius: 4, display: 'flex', alignItems: 'center' }}>
            <Icons.close color="currentColor" width={12} height={12} />
          </button>
        </div>
      ))}
    </div>
  );
}

// ─── Processing State ─────────────────────────────────────────────────────────
function ProcessingOverlay({ stage, progress, model }) {
  const stages = [
    { id: 'warmup', label: 'Loading model', icon: Icons.cpu },
    { id: 'detect', label: 'Detecting cards', icon: Icons.scan },
    { id: 'extract', label: 'Extracting data', icon: Icons.spark },
    { id: 'generate', label: 'Generating VCF', icon: Icons.download },
  ];
  const currentIdx = stages.findIndex(s => s.id === stage);

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)', padding: 24,
      display: 'flex', flexDirection: 'column', gap: 20,
    }}>
      {/* Model badge */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Processing…</div>
        <Badge label={model} color="blue" dot />
      </div>

      {/* Stage steps */}
      <div style={{ display: 'flex', gap: 0, position: 'relative' }}>
        {/* connecting line */}
        <div style={{ position: 'absolute', top: 15, left: '12.5%', right: '12.5%', height: 1, background: 'var(--border)', zIndex: 0 }} />
        {stages.map((s, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          const Icon = s.icon;
          return (
            <div key={s.id} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, position: 'relative', zIndex: 1 }}>
              <div style={{
                width: 30, height: 30, borderRadius: '50%',
                background: done ? 'var(--success)' : active ? 'var(--accent)' : 'var(--bg)',
                border: `1.5px solid ${done ? 'var(--success)' : active ? 'var(--accent)' : 'var(--border)'}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.3s',
                boxShadow: active ? '0 0 0 3px var(--accent-soft)' : 'none',
              }}>
                {done ? <Icons.check color="white" width={13} height={13} /> :
                  active ? <Spinner size={14} /> :
                  <Icon color="var(--text-tertiary)" width={13} height={13} />}
              </div>
              <div style={{ fontSize: 11, color: done ? 'var(--success)' : active ? 'var(--accent)' : 'var(--text-tertiary)', fontWeight: active ? 500 : 400, textAlign: 'center' }}>{s.label}</div>
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            {stages[currentIdx]?.label}
          </span>
          <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--accent)' }}>{progress}%</span>
        </div>
        <div style={{ height: 4, borderRadius: 99, background: 'var(--bg)', overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 99, background: 'var(--accent)',
            width: `${progress}%`, transition: 'width 0.4s ease',
          }} />
        </div>
      </div>
    </div>
  );
}

// ─── Contact Card (Result) ─────────────────────────────────────────────────────
function ContactCard({ card, onToggleLock, onSave }) {
  const [expanded, setExpanded] = useState(false);
  const [saved, setSaved] = useState(false);

  const c = card.contact;
  const initials = (c.fullName || '?').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
  const hue = ((c.fullName || '').split('').reduce((a, ch) => a + ch.charCodeAt(0), 0) * 37) % 360;

  const handleSave = () => {
    setSaved(true);
    onSave && onSave(card);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="pop-in" style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)', overflow: 'hidden',
      transition: 'box-shadow 0.2s',
      boxShadow: 'var(--shadow-sm)',
    }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = 'var(--shadow-md)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'var(--shadow-sm)'}
    >
      {/* Card header */}
      <div style={{ padding: '16px 16px 12px', display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* Avatar */}
        <div style={{
          width: 42, height: 42, borderRadius: 10, flexShrink: 0,
          background: `oklch(65% 0.15 ${hue})`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 15, fontWeight: 700, color: 'white', letterSpacing: '-0.01em',
        }}>
          {initials}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3 }}>{c.fullName}</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{c.title}</div>
            </div>
            <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
              <Badge label={card.via} color={card.via === 'QR Code' ? 'green' : 'blue'} dot />
            </div>
          </div>

          {c.company && (
            <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 5 }}>
              <Icons.building color="var(--text-tertiary)" width={12} height={12} />
              <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 500 }}>{c.company}</span>
            </div>
          )}
        </div>
      </div>

      <Divider />

      {/* Contact fields */}
      <div style={{ padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {c.email && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icons.email color="var(--text-tertiary)" />
            <span style={{ fontSize: 12, color: 'var(--text-primary)' }}>{c.email}</span>
          </div>
        )}
        {c.phone && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icons.phone color="var(--text-tertiary)" />
            <span style={{ fontSize: 12, color: 'var(--text-primary)' }}>{c.phone}</span>
          </div>
        )}
        {c.website && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icons.globe color="var(--text-tertiary)" />
            <span style={{ fontSize: 12, color: 'var(--accent)' }}>{c.website}</span>
          </div>
        )}
      </div>

      {/* Expanded fields */}
      {expanded && (
        <div className="fade-in" style={{ padding: '0 16px 10px', display: 'flex', flexDirection: 'column', gap: 5 }}>
          <Divider style={{ marginBottom: 8 }} />
          {c.mobile && c.mobile !== c.phone && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)', width: 52 }}>Mobile</span>
              <span style={{ fontSize: 12, color: 'var(--text-primary)' }}>{c.mobile}</span>
            </div>
          )}
          {c.linkedin && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Icons.linkedin color="var(--text-tertiary)" />
              <span style={{ fontSize: 12, color: 'var(--accent)' }}>{c.linkedin}</span>
            </div>
          )}
          {c.address && (
            <div style={{ display: 'flex', gap: 8 }}>
              <span style={{ fontSize: 11, color: 'var(--text-tertiary)', width: 52, flexShrink: 0 }}>Address</span>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{c.address}</span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)', width: 52 }}>Source</span>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{card.source}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)', width: 52 }}>Time</span>
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{card.time}s</span>
          </div>
        </div>
      )}

      <Divider />

      {/* Actions */}
      <div style={{ padding: '8px 12px', display: 'flex', gap: 6, alignItems: 'center' }}>
        <button
          onClick={() => setExpanded(e => !e)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, padding: '3px 6px', borderRadius: 4 }}
        >
          <Icons.chevronDown color="currentColor" style={{ transform: expanded ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s' }} />
          {expanded ? 'Less' : 'More'}
        </button>

        <div style={{ flex: 1 }} />

        <button
          onClick={() => onToggleLock && onToggleLock(card.id)}
          style={{ background: 'none', border: '1px solid var(--border)', cursor: 'pointer', color: card.locked ? 'var(--warning)' : 'var(--text-tertiary)', padding: '4px 8px', borderRadius: 5, display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontFamily: 'inherit' }}
        >
          <Icons.lock color="currentColor" />
          {card.locked ? 'Locked' : 'Lock'}
        </button>

        <Btn size="sm" icon={saved ? Icons.check : Icons.download} variant={saved ? 'success' : 'secondary'} onClick={handleSave}>
          {saved ? 'Saved' : '.vcf'}
        </Btn>
      </div>
    </div>
  );
}

// ─── Results Panel ────────────────────────────────────────────────────────────
function ResultsPanel({ cards, onToggleLock, onSave }) {
  const [view, setView] = useState('grid');
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [bulkSaved, setBulkSaved] = useState(false);

  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBulkDownload = () => {
    setBulkSaved(true);
    setTimeout(() => setBulkSaved(false), 2500);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      {/* Results toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}>
          {cards.length} contacts extracted
        </div>
        <div style={{ flex: 1 }} />

        {/* View toggle */}
        <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          {[['grid', Icons.grid], ['list', Icons.list]].map(([v, Icon]) => (
            <button key={v} onClick={() => setView(v)}
              style={{
                padding: '5px 8px', border: 'none', cursor: 'pointer',
                background: view === v ? 'var(--accent-soft)' : 'var(--surface)',
                color: view === v ? 'var(--accent)' : 'var(--text-tertiary)',
                transition: 'all 0.15s',
              }}>
              <Icon color="currentColor" width={14} height={14} />
            </button>
          ))}
        </div>

        <Btn size="sm" icon={Icons.download} variant="secondary">Export All</Btn>
        <Btn size="sm" icon={bulkSaved ? Icons.check : Icons.download} variant={bulkSaved ? 'success' : 'primary'} onClick={handleBulkDownload}>
          {bulkSaved ? 'Done!' : 'Download ZIP'}
        </Btn>
      </div>

      {/* Export format pills */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flexShrink: 0 }}>
        {['VCF', 'Excel', 'Outlook CSV'].map(fmt => (
          <button key={fmt}
            style={{
              padding: '4px 10px', borderRadius: 99, fontSize: 11, fontWeight: 500,
              border: '1px solid var(--border)', background: 'var(--surface)',
              color: 'var(--text-secondary)', cursor: 'pointer', fontFamily: 'inherit',
              display: 'flex', alignItems: 'center', gap: 5,
            }}>
            <Icons.download color="currentColor" width={10} height={10} />
            {fmt}
          </button>
        ))}
        <button style={{
          padding: '4px 10px', borderRadius: 99, fontSize: 11, fontWeight: 500,
          border: '1px solid var(--border)', background: 'var(--bg)',
          color: 'var(--text-tertiary)', cursor: 'pointer', fontFamily: 'inherit',
        }}>
          + Outlook Push
        </button>
      </div>

      {/* Cards grid/list */}
      <div style={{
        flex: 1, overflowY: 'auto',
        display: view === 'grid' ? 'grid' : 'flex',
        gridTemplateColumns: view === 'grid' ? 'repeat(auto-fill, minmax(280px, 1fr))' : undefined,
        flexDirection: view === 'list' ? 'column' : undefined,
        gap: 12, paddingRight: 2, paddingBottom: 8,
        alignContent: 'start',
      }}>
        {cards.map((card, i) => (
          <div key={card.id} style={{ animationDelay: `${i * 0.05}s` }}>
            <ContactCard card={card} onToggleLock={onToggleLock} onSave={onSave} />
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Scanner Tab ──────────────────────────────────────────────────────────────
function ScannerTab({ tweaks, densityPad }) {
  const [files, setFiles] = useState([]);
  const [config, setConfig] = useState({ model: 'glm-ocr', mode: 'auto', rows: 4, cols: 2, timeout: 300 });
  const [phase, setPhase] = useState('idle'); // idle | processing | results
  const [stage, setStage] = useState('warmup');
  const [progress, setProgress] = useState(0);
  const [cards, setCards] = useState([]);

  const handleFilesAdded = (newFiles) => {
    setFiles(prev => [...prev, ...newFiles.map(f => ({ name: f.name, size: f.size }))]);
  };

  const handleProcess = () => {
    if (!files.length) return;
    setPhase('processing');
    setProgress(0);
    setStage('warmup');

    // Simulate processing pipeline
    const steps = [
      { stage: 'warmup', target: 18, delay: 800 },
      { stage: 'detect', target: 40, delay: 900 },
      { stage: 'extract', target: 85, delay: 2200 },
      { stage: 'generate', target: 100, delay: 700 },
    ];

    let total = 0;
    steps.forEach(({ stage: s, target, delay }, i) => {
      total += delay;
      setTimeout(() => setStage(s), steps.slice(0, i).reduce((a, x) => a + x.delay, 0));
      setTimeout(() => setProgress(target), total);
    });

    setTimeout(() => {
      setCards(MOCK_RESULTS);
      setPhase('results');
    }, total + 200);
  };

  const handleReset = () => {
    setPhase('idle');
    setFiles([]);
    setCards([]);
    setProgress(0);
  };

  const handleToggleLock = (id) => {
    setCards(prev => prev.map(c => c.id === id ? { ...c, locked: !c.locked } : c));
  };

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', gap: 0 }}>
      {/* Left: Input panel */}
      <div style={{
        width: 320, flexShrink: 0,
        borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', gap: 0,
        overflowY: 'auto', background: 'var(--surface)',
      }}>
        <div style={{ padding: densityPad, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Upload zone */}
          <UploadZone onFilesAdded={handleFilesAdded} />

          {/* File queue */}
          {files.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-secondary)' }}>{files.length} file{files.length !== 1 ? 's' : ''} queued</span>
                <button onClick={() => setFiles([])}
                  style={{ fontSize: 11, color: 'var(--text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px' }}>
                  Clear all
                </button>
              </div>
              <FileQueue files={files} onRemove={i => setFiles(prev => prev.filter((_, idx) => idx !== i))} />
            </div>
          )}

          {/* Config */}
          <ConfigPanel config={config} onChange={setConfig} />
        </div>

        {/* Sticky process button */}
        <div style={{
          marginTop: 'auto', padding: 16, borderTop: '1px solid var(--border)',
          position: 'sticky', bottom: 0, background: 'var(--surface)',
        }}>
          {phase === 'results' ? (
            <div style={{ display: 'flex', gap: 8 }}>
              <Btn variant="ghost" style={{ flex: 1 }} onClick={handleReset} icon={Icons.refresh}>New Scan</Btn>
              <Btn variant="primary" style={{ flex: 1 }} icon={Icons.plus} onClick={() => setPhase('idle')}>Add More</Btn>
            </div>
          ) : (
            <Btn
              variant="primary"
              size="lg"
              style={{ width: '100%', justifyContent: 'center' }}
              icon={phase === 'processing' ? undefined : Icons.scan}
              disabled={!files.length || phase === 'processing'}
              onClick={handleProcess}
            >
              {phase === 'processing' ? (
                <><Spinner size={14} /> Processing…</>
              ) : (
                `Process ${files.length ? `${files.length} file${files.length !== 1 ? 's' : ''}` : 'Cards'}`
              )}
            </Btn>
          )}
        </div>
      </div>

      {/* Right: Results / Processing area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: densityPad, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {phase === 'idle' && (
          <div className="fade-in" style={{
            flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: 16, color: 'var(--text-tertiary)', textAlign: 'center', paddingTop: 40,
          }}>
            <div style={{
              width: 72, height: 72, borderRadius: 18, background: 'var(--surface)',
              border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: 'var(--shadow-sm)',
            }}>
              <Icons.card color="var(--border-strong)" width={32} height={32} />
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--text-secondary)', marginBottom: 6 }}>No cards processed yet</div>
              <div style={{ fontSize: 13, color: 'var(--text-tertiary)', maxWidth: 320, lineHeight: 1.6 }}>
                Upload images on the left and click Process to extract contact data automatically.
              </div>
            </div>

            {/* Tips */}
            <div style={{
              marginTop: 8, background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: 10, padding: '14px 18px', width: '100%', maxWidth: 380,
            }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 10 }}>Quick tips</div>
              {[
                ['GLM-OCR is fastest', 'Only 0.9B params, loads in seconds'],
                ['QR codes auto-skip vision', 'Saves 20–30s when QR has email'],
                ['Batch scans supported', 'Upload a grid of cards as one image'],
              ].map(([title, desc]) => (
                <div key={title} style={{ display: 'flex', gap: 10, marginBottom: 8, alignItems: 'flex-start' }}>
                  <Icons.bolt color="var(--accent)" width={12} height={12} style={{ marginTop: 2, flexShrink: 0 }} />
                  <div>
                    <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-primary)' }}>{title} — </span>
                    <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {phase === 'processing' && (
          <div className="fade-in" style={{ maxWidth: 480, width: '100%', margin: '40px auto 0' }}>
            <ProcessingOverlay stage={stage} progress={progress} model={config.model} />
          </div>
        )}

        {phase === 'results' && (
          <div className="fade-in" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Run summary */}
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10,
            }}>
              {[
                { label: 'Cards found', value: cards.length, color: 'var(--accent)' },
                { label: 'With email', value: cards.filter(c => c.contact.email).length, color: 'var(--success)' },
                { label: 'Via QR', value: cards.filter(c => c.via === 'QR Code').length, color: 'var(--warning)' },
                { label: 'Avg time', value: `${(cards.reduce((a, c) => a + c.time, 0) / cards.length).toFixed(1)}s`, color: 'var(--text-primary)' },
              ].map(({ label, value, color }) => (
                <div key={label} style={{
                  background: 'var(--surface)', border: '1px solid var(--border)',
                  borderRadius: 8, padding: '12px 14px',
                }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color, letterSpacing: '-0.02em' }}>{value}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>

            <ResultsPanel cards={cards} onToggleLock={handleToggleLock} />
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { ScannerTab, Btn, Badge, Spinner, Divider, ContactCard });
