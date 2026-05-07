// Contacts Repository Tab
const { useState, useMemo } = React;

const MOCK_CONTACTS = [
  { id: 'c001', addedAt: '2026-04-28', source: 'batch1.jpg', vcf: true, contact: { fullName: 'Marco Ribeiro', title: 'Head of Engineering', company: 'Steinweg Brokers', email: 'marco.ribeiro@steinweg.com', phone: '+55 11 9 8765-4321', website: 'steinweg.com', linkedin: 'linkedin.com/in/marcoribeiro', address: 'Av. Paulista, 1234 — São Paulo, SP' }},
  { id: 'c002', addedAt: '2026-04-28', source: 'batch1.jpg', vcf: true, contact: { fullName: 'Ana Costa', title: 'Director of Sales', company: 'Nexus Capital', email: 'ana.costa@nexuscap.com', phone: '+55 21 98800-1234', website: 'nexuscapital.com.br', linkedin: '', address: 'Rua da Quitanda, 86 — Rio, RJ' }},
  { id: 'c003', addedAt: '2026-04-29', source: 'cards_eu.pdf', vcf: true, contact: { fullName: 'Pierre Dupont', title: 'Investment Manager', company: 'Société Générale', email: 'p.dupont@socgen.fr', phone: '+33 1 42 14 20 00', website: 'societegenerale.com', linkedin: 'linkedin.com/in/pierredupont', address: '29 Blvd Haussmann, Paris' }},
  { id: 'c004', addedAt: '2026-04-29', source: 'cards_eu.pdf', vcf: true, contact: { fullName: 'Yuki Tanaka', title: 'CTO', company: 'Fujitsu Corp.', email: 'y.tanaka@fujitsu.com', phone: '+81 3 6252-2220', website: 'fujitsu.com', linkedin: '', address: 'Shibuya-ku, Tokyo, Japan' }},
  { id: 'c005', addedAt: '2026-04-30', source: 'scan_may.jpg', vcf: false, contact: { fullName: 'Beatriz Melo', title: 'Marketing Manager', company: 'Nexus Capital', email: 'b.melo@nexuscap.com', phone: '+55 21 3200-0000', website: '', linkedin: 'linkedin.com/in/beatrizmelo', address: '' }},
  { id: 'c006', addedAt: '2026-05-01', source: 'scan_may.jpg', vcf: true, contact: { fullName: 'Klaus Bauer', title: 'Partner', company: 'Bauer & Associates', email: 'k.bauer@bauer-assoc.de', phone: '+49 30 2020-3030', website: 'bauer-assoc.de', linkedin: '', address: 'Unter den Linden 5, Berlin' }},
  { id: 'c007', addedAt: '2026-05-01', source: 'scan_may.jpg', vcf: true, contact: { fullName: 'Laila Hassan', title: 'Operations Director', company: 'Gulf Trade Co.', email: 'l.hassan@gulftrade.ae', phone: '+971 4 321 0000', website: 'gulftrade.ae', linkedin: 'linkedin.com/in/lailahassan', address: 'Dubai, UAE' }},
  { id: 'c008', addedAt: '2026-05-02', source: 'steinweg_batch.pdf', vcf: true, contact: { fullName: 'Rafael Santos', title: 'Senior Broker', company: 'Steinweg Brokers', email: 'r.santos@steinweg.com', phone: '+55 11 3333-4444', website: 'steinweg.com', linkedin: '', address: 'Av. Paulista, 1234 — São Paulo, SP' }},
];

function StatCard({ value, label, accent }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 16px' }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent || 'var(--text-primary)', letterSpacing: '-0.03em' }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>{label}</div>
    </div>
  );
}

function ContactRow({ contact: c, selected, onSelect, onDelete, expanded, onToggleExpand }) {
  const initials = (c.contact.fullName || '?').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
  const hue = ((c.contact.fullName || '').split('').reduce((a, ch) => a + ch.charCodeAt(0), 0) * 37) % 360;

  return (
    <div style={{
      background: selected ? 'var(--accent-soft)' : 'var(--surface)',
      border: `1px solid ${selected ? 'oklch(85% 0.08 264)' : 'var(--border)'}`,
      borderRadius: 8, overflow: 'hidden',
      transition: 'all 0.15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px' }}>
        {/* Checkbox */}
        <div
          onClick={onSelect}
          style={{
            width: 16, height: 16, borderRadius: 4, flexShrink: 0, cursor: 'pointer',
            border: `1.5px solid ${selected ? 'var(--accent)' : 'var(--border-strong)'}`,
            background: selected ? 'var(--accent)' : 'transparent',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          {selected && <Icons.check color="white" width={10} height={10} />}
        </div>

        {/* Avatar */}
        <div style={{
          width: 34, height: 34, borderRadius: 8, flexShrink: 0,
          background: `oklch(65% 0.15 ${hue})`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 700, color: 'white',
        }}>
          {initials}
        </div>

        {/* Name + details */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{c.contact.fullName}</span>
            {c.contact.title && <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{c.contact.title}</span>}
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 2, flexWrap: 'wrap' }}>
            {c.contact.company && <span style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 3 }}><Icons.building color="currentColor" width={10} height={10} />{c.contact.company}</span>}
            {c.contact.email && <span style={{ fontSize: 11, color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center', gap: 3 }}><Icons.email color="currentColor" width={10} height={10} />{c.contact.email}</span>}
          </div>
        </div>

        {/* Right side */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{c.addedAt}</span>
          <button
            onClick={onToggleExpand}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 4, display: 'flex', alignItems: 'center' }}>
            <Icons.chevronDown color="currentColor" style={{ transform: expanded ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s' }} />
          </button>
          <button onClick={onDelete}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', padding: 4, display: 'flex', alignItems: 'center', borderRadius: 4 }}
            onMouseEnter={e => e.currentTarget.style.color = 'var(--danger)'}
            onMouseLeave={e => e.currentTarget.style.color = 'var(--text-tertiary)'}
          >
            <Icons.trash color="currentColor" />
          </button>
        </div>
      </div>

      {/* Expanded detail row */}
      {expanded && (
        <div className="fade-in" style={{ borderTop: '1px solid var(--border)', padding: '10px 14px 12px', display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 200 }}>
            {c.contact.phone && <Detail icon={Icons.phone} label="Phone" value={c.contact.phone} />}
            {c.contact.website && <Detail icon={Icons.globe} label="Website" value={c.contact.website} accent />}
            {c.contact.linkedin && <Detail icon={Icons.linkedin} label="LinkedIn" value={c.contact.linkedin} accent />}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minWidth: 200 }}>
            {c.contact.address && <Detail icon={Icons.building} label="Address" value={c.contact.address} />}
            <Detail icon={Icons.card} label="Source" value={c.source} />
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'flex-start', gap: 6 }}>
            {c.vcf && <Btn size="sm" icon={Icons.download} variant="secondary">.vcf</Btn>}
          </div>
        </div>
      )}
    </div>
  );
}

function Detail({ icon: Icon, label, value, accent }) {
  return (
    <div style={{ display: 'flex', gap: 7, alignItems: 'flex-start' }}>
      <Icon color="var(--text-tertiary)" style={{ marginTop: 2, flexShrink: 0 }} />
      <div>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{label}: </span>
        <span style={{ fontSize: 12, color: accent ? 'var(--accent)' : 'var(--text-primary)' }}>{value}</span>
      </div>
    </div>
  );
}

function CompanyGroup({ company, contacts, selectedIds, onSelect, onDelete, expandedId, onToggleExpand }) {
  const hue = (company.split('').reduce((a, ch) => a + ch.charCodeAt(0), 0) * 53) % 360;
  const [groupExpanded, setGroupExpanded] = useState(true);
  const allSelected = contacts.every(c => selectedIds.has(c.id));

  const toggleAll = () => {
    contacts.forEach(c => onSelect(c.id, !allSelected));
  };

  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '7px 12px', borderRadius: 7,
        background: `oklch(65% 0.14 ${hue} / 0.08)`,
        border: `1px solid oklch(65% 0.14 ${hue} / 0.2)`,
        cursor: 'pointer', userSelect: 'none',
        marginBottom: 6,
      }}
        onClick={() => setGroupExpanded(e => !e)}
      >
        <div
          onClick={e => { e.stopPropagation(); toggleAll(); }}
          style={{
            width: 16, height: 16, borderRadius: 4, flexShrink: 0, cursor: 'pointer',
            border: `1.5px solid ${allSelected ? `oklch(55% 0.22 ${hue})` : 'var(--border-strong)'}`,
            background: allSelected ? `oklch(55% 0.22 ${hue})` : 'transparent',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          {allSelected && <Icons.check color="white" width={10} height={10} />}
        </div>

        <div style={{ width: 8, height: 8, borderRadius: '50%', background: `oklch(55% 0.18 ${hue})`, flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', flex: 1 }}>{company}</span>
        <span style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{contacts.length} contact{contacts.length !== 1 ? 's' : ''}</span>
        <Icons.chevronDown color="var(--text-tertiary)" style={{ transform: groupExpanded ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s' }} />
      </div>

      {groupExpanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5, paddingLeft: 10 }}>
          {contacts.map(c => (
            <ContactRow
              key={c.id}
              contact={c}
              selected={selectedIds.has(c.id)}
              onSelect={() => onSelect(c.id)}
              onDelete={() => onDelete(c.id)}
              expanded={expandedId === c.id}
              onToggleExpand={() => onToggleExpand(c.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ContactsTab({ tweaks, densityPad }) {
  const [contacts, setContacts] = useState(MOCK_CONTACTS);
  const [search, setSearch] = useState('');
  const [groupByCompany, setGroupByCompany] = useState(true);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [expandedId, setExpandedId] = useState(null);
  const [exportDone, setExportDone] = useState('');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return contacts;
    return contacts.filter(c =>
      [c.contact.fullName, c.contact.company, c.contact.email, c.contact.phone]
        .some(v => v && v.toLowerCase().includes(q))
    );
  }, [contacts, search]);

  const grouped = useMemo(() => {
    const g = {};
    filtered.forEach(c => {
      const key = c.contact.company || '(No company)';
      if (!g[key]) g[key] = [];
      g[key].push(c);
    });
    return Object.entries(g).sort(([a], [b]) => (a === '(No company)' ? 1 : b === '(No company)' ? -1 : a.localeCompare(b)));
  }, [filtered]);

  const toggleSelect = (id, force) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (force === true) next.add(id);
      else if (force === false) next.delete(id);
      else if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleDelete = (id) => setContacts(prev => prev.filter(c => c.id !== id));
  const handleToggleExpand = (id) => setExpandedId(prev => prev === id ? null : id);

  const handleExport = (fmt) => {
    setExportDone(fmt);
    setTimeout(() => setExportDone(''), 2000);
  };

  const stats = {
    total: contacts.length,
    withEmail: contacts.filter(c => c.contact.email).length,
    withPhone: contacts.filter(c => c.contact.phone).length,
    companies: new Set(contacts.map(c => c.contact.company).filter(Boolean)).size,
  };

  const allFilteredSelected = filtered.length > 0 && filtered.every(c => selectedIds.has(c.id));
  const toggleAll = () => {
    if (allFilteredSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(filtered.map(c => c.id)));
  };

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Stats bar */}
      <div style={{ padding: `${densityPad}px ${densityPad}px 0`, flexShrink: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 16 }}>
          <StatCard value={stats.total} label="Total contacts" accent="var(--accent)" />
          <StatCard value={stats.withEmail} label="With email" accent="var(--success)" />
          <StatCard value={stats.withPhone} label="With phone" />
          <StatCard value={stats.companies} label="Companies" accent="var(--warning)" />
        </div>

        {/* Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          {/* Search */}
          <div style={{ position: 'relative', flex: 1, maxWidth: 380 }}>
            <Icons.search color="var(--text-tertiary)" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by name, company, email…"
              style={{
                width: '100%', padding: '7px 12px 7px 32px',
                border: '1px solid var(--border)', borderRadius: 6,
                background: 'var(--surface)', fontSize: 13, fontFamily: 'inherit',
                color: 'var(--text-primary)', outline: 'none',
              }}
              onFocus={e => e.target.style.borderColor = 'var(--accent)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />
            {search && (
              <button onClick={() => setSearch('')}
                style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-tertiary)', display: 'flex', alignItems: 'center' }}>
                <Icons.close color="currentColor" />
              </button>
            )}
          </div>

          {/* Group toggle */}
          <button
            onClick={() => setGroupByCompany(g => !g)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 12px', border: '1px solid var(--border)', borderRadius: 6,
              background: groupByCompany ? 'var(--accent-soft)' : 'var(--surface)',
              color: groupByCompany ? 'var(--accent)' : 'var(--text-secondary)',
              fontSize: 12, fontFamily: 'inherit', fontWeight: 500, cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            <Icons.grid color="currentColor" />
            Group by company
          </button>

          <div style={{ flex: 1 }} />

          {/* Export buttons */}
          <div style={{ display: 'flex', gap: 6 }}>
            {['VCF', 'Excel', 'CSV'].map(fmt => (
              <Btn key={fmt} size="sm" variant={exportDone === fmt ? 'success' : 'secondary'}
                icon={exportDone === fmt ? Icons.check : Icons.download}
                onClick={() => handleExport(fmt)}>
                {exportDone === fmt ? 'Done' : fmt}
              </Btn>
            ))}
          </div>

          <Btn size="sm" variant="danger" icon={Icons.trash}
            disabled={selectedIds.size === 0}
            onClick={() => { setContacts(c => c.filter(x => !selectedIds.has(x.id))); setSelectedIds(new Set()); }}>
            Delete {selectedIds.size > 0 ? `(${selectedIds.size})` : ''}
          </Btn>
        </div>

        {/* Bulk selection bar */}
        {filtered.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, marginBottom: 10, fontSize: 12 }}>
            <div
              onClick={toggleAll}
              style={{
                width: 16, height: 16, borderRadius: 4, flexShrink: 0, cursor: 'pointer',
                border: `1.5px solid ${allFilteredSelected ? 'var(--accent)' : 'var(--border-strong)'}`,
                background: allFilteredSelected ? 'var(--accent)' : 'transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              {allFilteredSelected && <Icons.check color="white" width={10} height={10} />}
            </div>
            <span style={{ color: 'var(--text-secondary)' }}>
              {selectedIds.size > 0
                ? <><strong>{selectedIds.size}</strong> selected</>
                : <span style={{ color: 'var(--text-tertiary)' }}>Select all</span>
              }
            </span>
            {search && <Badge label={`${filtered.length} results`} color="blue" />}
          </div>
        )}
      </div>

      {/* Contact list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: `0 ${densityPad}px ${densityPad}px` }}>
        {contacts.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, paddingTop: 60, color: 'var(--text-tertiary)', textAlign: 'center' }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, background: 'var(--surface)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Icons.contacts color="var(--border-strong)" width={24} height={24} />
            </div>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--text-secondary)' }}>No contacts yet</div>
            <div style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Process business cards to populate your repository.</div>
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-tertiary)', fontSize: 13 }}>
            No contacts match "<strong>{search}</strong>"
          </div>
        ) : groupByCompany ? (
          grouped.map(([company, contacts]) => (
            <CompanyGroup
              key={company}
              company={company}
              contacts={contacts}
              selectedIds={selectedIds}
              onSelect={toggleSelect}
              onDelete={handleDelete}
              expandedId={expandedId}
              onToggleExpand={handleToggleExpand}
            />
          ))
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {filtered.map(c => (
              <ContactRow
                key={c.id}
                contact={c}
                selected={selectedIds.has(c.id)}
                onSelect={() => toggleSelect(c.id)}
                onDelete={() => handleDelete(c.id)}
                expanded={expandedId === c.id}
                onToggleExpand={() => handleToggleExpand(c.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { ContactsTab });
