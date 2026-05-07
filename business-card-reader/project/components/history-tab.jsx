// History Tab Component
const { useState, useMemo: useMemo2 } = React;

const MOCK_RUNS = [
  {
    id: '20260502_143021_a1b2c3',
    createdAt: '2026-05-02T14:30:21',
    settings: { vision_model: 'glm-ocr', detection_mode: 'Automatic', vision_timeout: 300 },
    cards: [
      { contact: { fullName: 'Marco Ribeiro', company: 'Steinweg Brokers', email: 'marco.ribeiro@steinweg.com', phone: '+55 11 9 8765-4321' } },
      { contact: { fullName: 'Ana Costa', company: 'Nexus Capital', email: 'ana.costa@nexuscap.com', phone: '+55 21 98800-1234' } },
      { contact: { fullName: 'Rafael Santos', company: 'Steinweg Brokers', email: 'r.santos@steinweg.com', phone: '' } },
    ],
    originalFiles: ['steinweg_batch.pdf'],
    exports: ['contacts.vcf', 'contacts.xlsx'],
  },
  {
    id: '20260501_092314_d4e5f6',
    createdAt: '2026-05-01T09:23:14',
    settings: { vision_model: 'glm-ocr', detection_mode: 'Manual - Grid Layout', vision_timeout: 300 },
    cards: [
      { contact: { fullName: 'Klaus Bauer', company: 'Bauer & Associates', email: 'k.bauer@bauer-assoc.de', phone: '+49 30 2020-3030' } },
      { contact: { fullName: 'Laila Hassan', company: 'Gulf Trade Co.', email: 'l.hassan@gulftrade.ae', phone: '+971 4 321 0000' } },
    ],
    originalFiles: ['scan_may.jpg'],
    exports: ['contacts.vcf'],
  },
  {
    id: '20260429_161050_g7h8i9',
    createdAt: '2026-04-29T16:10:50',
    settings: { vision_model: 'llama3.2-vision', detection_mode: 'Automatic', vision_timeout: 300 },
    cards: [
      { contact: { fullName: 'Pierre Dupont', company: 'Société Générale', email: 'p.dupont@socgen.fr', phone: '+33 1 42 14 20 00' } },
      { contact: { fullName: 'Yuki Tanaka', company: 'Fujitsu Corp.', email: 'y.tanaka@fujitsu.com', phone: '+81 3 6252-2220' } },
    ],
    originalFiles: ['cards_eu.pdf'],
    exports: ['contacts.vcf', 'contacts.xlsx', 'contacts_outlook.csv'],
  },
  {
    id: '20260428_112233_j0k1l2',
    createdAt: '2026-04-28T11:22:33',
    settings: { vision_model: 'glm-ocr', detection_mode: 'Automatic', vision_timeout: 300 },
    cards: [
      { contact: { fullName: 'Marco Ribeiro', company: 'Steinweg Brokers', email: 'marco.ribeiro@steinweg.com', phone: '' } },
      { contact: { fullName: 'Ana Costa', company: 'Nexus Capital', email: 'ana.costa@nexuscap.com', phone: '' } },
      { contact: { fullName: 'Beatriz Melo', company: 'Nexus Capital', email: 'b.melo@nexuscap.com', phone: '' } },
    ],
    originalFiles: ['batch1.jpg', 'batch2.jpg'],
    exports: ['contacts.vcf', 'contacts.xlsx'],
  },
  {
    id: '20260409_153412_m3n4o5',
    createdAt: '2026-04-09T15:34:12',
    settings: { vision_model: 'claude-3', detection_mode: 'Manual - Single Card', vision_timeout: 120 },
    cards: [
      { contact: { fullName: 'Isabella Romano', company: 'UniCredit', email: 'i.romano@unicredit.it', phone: '+39 02 8862 1' } },
    ],
    originalFiles: ['card_milan.jpg'],
    exports: [],
  },
];

function TimelineDot({ active }) {
  return (
    <div style={{
      width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
      background: active ? 'var(--accent)' : 'var(--border-strong)',
      border: `2px solid ${active ? 'var(--accent-soft)' : 'var(--surface)'}`,
      boxShadow: active ? '0 0 0 2px var(--accent-soft)' : 'none',
      transition: 'all 0.2s',
    }} />
  );
}

function RunCard({ run, expanded, onToggle, onRelaunch, onDelete }) {
  const dt = new Date(run.createdAt);
  const dateStr = dt.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
  const timeStr = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const emailCount = run.cards.filter(c => c.contact.email).length;
  const phoneCount = run.cards.filter(c => c.contact.phone).length;

  const modelColor = run.settings.vision_model === 'glm-ocr' ? 'green'
    : run.settings.vision_model.startsWith('claude') ? 'amber' : 'blue';

  return (
    <div style={{ display: 'flex', gap: 0 }}>
      {/* Timeline */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 28, flexShrink: 0, paddingTop: 14 }}>
        <TimelineDot active={expanded} />
        <div style={{ flex: 1, width: 1.5, background: 'var(--border)', marginTop: 4 }} />
      </div>

      {/* Card */}
      <div style={{ flex: 1, marginLeft: 10, marginBottom: 12 }}>
        <div
          style={{
            background: 'var(--surface)', border: `1px solid ${expanded ? 'oklch(85% 0.08 264)' : 'var(--border)'}`,
            borderRadius: 10, overflow: 'hidden', transition: 'all 0.2s',
            boxShadow: expanded ? 'var(--shadow-md)' : 'var(--shadow-sm)',
          }}
        >
          {/* Header */}
          <div
            onClick={onToggle}
            style={{ padding: '12px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}
          >
            {/* Date/time */}
            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{dateStr}</span>
                <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{timeStr}</span>
                <Badge label={run.settings.vision_model} color={modelColor} />
                <Badge label={run.settings.detection_mode.replace('Manual - ', '')} color="neutral" />
              </div>
              <div style={{ marginTop: 4, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                  <strong style={{ color: 'var(--text-primary)' }}>{run.cards.length}</strong> cards
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                  <strong style={{ color: 'var(--success)' }}>{emailCount}</strong> emails
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                  <strong style={{ color: 'var(--text-primary)' }}>{phoneCount}</strong> phones
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>
                  {run.originalFiles.length} file{run.originalFiles.length !== 1 ? 's' : ''}
                </span>
              </div>
            </div>

            <div style={{ flex: 1 }} />

            {/* Action buttons */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <Btn size="sm" variant="secondary" icon={Icons.refresh} onClick={e => { e.stopPropagation(); onRelaunch(run.id); }}>
                Relaunch
              </Btn>
              <Btn size="sm" variant="secondary" icon={Icons.download} onClick={e => e.stopPropagation()}>
                ZIP
              </Btn>
              <button
                onClick={e => { e.stopPropagation(); onDelete(run.id); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: '4px 6px', display: 'flex', alignItems: 'center', borderRadius: 4 }}
                onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
                onMouseLeave={e => e.currentTarget.style.color = 'var(--text-tertiary)'}
              >
                <Icons.trash color="currentColor" />
              </button>
              <Icons.chevronDown
                color="var(--text-tertiary)"
                style={{ transform: expanded ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.2s' }}
              />
            </div>
          </div>

          {/* Expanded content */}
          {expanded && (
            <div className="fade-in">
              <Divider />
              <div style={{ padding: '12px 16px', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                {/* Contacts list */}
                <div style={{ flex: 2, minWidth: 260 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Contacts</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {run.cards.map((card, i) => {
                      const initials = (card.contact.fullName || '?').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
                      const hue = ((card.contact.fullName || '').split('').reduce((a, ch) => a + ch.charCodeAt(0), 0) * 37) % 360;
                      return (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', background: 'var(--bg)', borderRadius: 6 }}>
                          <div style={{ width: 26, height: 26, borderRadius: 6, flexShrink: 0, background: `oklch(65% 0.15 ${hue})`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 700, color: 'white' }}>{initials}</div>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{card.contact.fullName}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{card.contact.company}</div>
                          </div>
                          {card.contact.email && <Icons.email color="var(--success)" />}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Sidebar meta */}
                <div style={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {/* Source files */}
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Source files</div>
                    {run.originalFiles.map(f => (
                      <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)', marginBottom: 3 }}>
                        <Icons.card color="var(--text-tertiary)" width={12} height={12} />
                        {f}
                      </div>
                    ))}
                  </div>

                  {/* Exports */}
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Exports</div>
                    {run.exports.length === 0 ? (
                      <div style={{ fontSize: 12, color: 'var(--text-tertiary)', fontStyle: 'italic' }}>No exports archived</div>
                    ) : run.exports.map(f => (
                      <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)', marginBottom: 3 }}>
                        <Icons.download color="var(--text-tertiary)" width={12} height={12} />
                        {f}
                      </div>
                    ))}
                  </div>

                  {/* Settings */}
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Settings</div>
                    <div style={{ fontSize: 11, color: 'var(--text-tertiary)', lineHeight: 1.8 }}>
                      <div>Model: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{run.settings.vision_model}</span></div>
                      <div>Mode: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{run.settings.detection_mode}</span></div>
                      <div>Timeout: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{run.settings.vision_timeout}s</span></div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Run ID */}
              <div style={{ padding: '8px 16px', borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
                <span style={{ fontSize: 10, color: 'var(--text-tertiary)', fontFamily: 'monospace' }}>Run ID: {run.id}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function HistoryTab({ tweaks, densityPad }) {
  const [runs, setRuns] = useState(MOCK_RUNS);
  const [expandedId, setExpandedId] = useState(null);
  const [relaunching, setRelaunching] = useState(null);
  const [filterModel, setFilterModel] = useState('all');

  const models = useMemo2(() => {
    const s = new Set(runs.map(r => r.settings.vision_model));
    return ['all', ...Array.from(s)];
  }, [runs]);

  const filtered = useMemo2(() =>
    filterModel === 'all' ? runs : runs.filter(r => r.settings.vision_model === filterModel),
    [runs, filterModel]
  );

  const handleRelaunch = (id) => {
    setRelaunching(id);
    setTimeout(() => setRelaunching(null), 2000);
  };

  const handleDelete = (id) => {
    setRuns(prev => prev.filter(r => r.id !== id));
    if (expandedId === id) setExpandedId(null);
  };

  const totalCards = runs.reduce((a, r) => a + r.cards.length, 0);
  const totalEmails = runs.reduce((a, r) => a + r.cards.filter(c => c.contact.email).length, 0);

  // Group by date
  const byDate = useMemo2(() => {
    const g = {};
    filtered.forEach(run => {
      const date = new Date(run.createdAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' });
      if (!g[date]) g[date] = [];
      g[date].push(run);
    });
    return Object.entries(g);
  }, [filtered]);

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Stats + toolbar */}
      <div style={{ padding: `${densityPad}px ${densityPad}px 0`, flexShrink: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
          <StatCard value={runs.length} label="Total runs" accent="var(--accent)" />
          <StatCard value={totalCards} label="Total cards" accent="var(--text-primary)" />
          <StatCard value={totalEmails} label="Emails extracted" accent="var(--success)" />
          <StatCard value={runs.reduce((a, r) => a + r.originalFiles.length, 0)} label="Source files" />
        </div>

        {/* Filter bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, padding: '6px 10px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 7 }}>
          <Icons.filter color="var(--text-tertiary)" width={13} height={13} />
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)', fontWeight: 500 }}>Model:</span>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {models.map(m => (
              <button key={m}
                onClick={() => setFilterModel(m)}
                style={{
                  padding: '3px 9px', borderRadius: 99, fontSize: 11, fontWeight: 500,
                  border: '1px solid', cursor: 'pointer', fontFamily: 'inherit',
                  borderColor: filterModel === m ? 'var(--accent)' : 'var(--border)',
                  background: filterModel === m ? 'var(--accent-soft)' : 'transparent',
                  color: filterModel === m ? 'var(--accent)' : 'var(--text-secondary)',
                  transition: 'all 0.15s',
                }}
              >
                {m}
              </button>
            ))}
          </div>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{filtered.length} run{filtered.length !== 1 ? 's' : ''}</span>
        </div>
      </div>

      {/* Timeline */}
      <div style={{ flex: 1, overflowY: 'auto', padding: `0 ${densityPad}px ${densityPad}px` }}>
        {runs.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, paddingTop: 60, color: 'var(--text-tertiary)', textAlign: 'center' }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, background: 'var(--surface)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icons.history color="var(--border-strong)" width={24} height={24} />
            </div>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-secondary)' }}>No scan history</div>
            <div style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Past scanning sessions appear here automatically.</div>
          </div>
        ) : (
          byDate.map(([date, dateRuns]) => (
            <div key={date} style={{ marginBottom: 4 }}>
              {/* Date label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>{date}</div>
                <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
              </div>

              {dateRuns.map(run => (
                <div key={run.id} style={{ position: 'relative' }}>
                  {relaunching === run.id && (
                    <div className="fade-in" style={{
                      position: 'absolute', inset: 0, zIndex: 10, background: 'oklch(100% 0 0 / 0.85)',
                      borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, backdropFilter: 'blur(2px)',
                    }}>
                      <Spinner size={18} />
                      <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--accent)' }}>Relaunching…</span>
                    </div>
                  )}
                  <RunCard
                    run={run}
                    expanded={expandedId === run.id}
                    onToggle={() => setExpandedId(prev => prev === run.id ? null : run.id)}
                    onRelaunch={handleRelaunch}
                    onDelete={handleDelete}
                  />
                </div>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

Object.assign(window, { HistoryTab, StatCard });
