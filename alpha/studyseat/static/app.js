/* API transport, rendering, and event handlers keep server decisions authoritative. */
let csrfToken = '';
// Identity transitions invalidate every private response; query edits invalidate seats only.
let identityGeneration = 0;
let seatQueryGeneration = 0;
let reservationListGeneration = 0;
let identityKey = '';
let pendingBooking = null;
const busyButtons = new WeakMap();
const element = id => document.getElementById(id);
class StaleResponse extends Error {}

function clearLoadedData() {
  ++reservationListGeneration;
  clearAdminState();
  for (const id of ['rooms', 'rules', 'notes', 'events', 'reservations', 'seat-id', 'room-id']) element(id).replaceChildren();
  element('admin').hidden = true;
  element('student-booking').hidden = true;
  element('booking-form').hidden = true;
  invalidateSeats();
  element('search-fields').disabled = true;
  element('initialization-state').textContent = '正在加载工作台…';
  element('reload-dashboard').hidden = true;
}

function clearPrivateState() {
  clearLoadedData();
  for (const id of ['welcome', 'identity']) element(id).textContent = '';
  for (const id of ['note', 'password']) element(id).value = '';
  identityKey = '';
  pendingBooking = null;
  element('start-at').value = '';
  element('end-at').value = '';
}

async function api(path, options = {}, epoch = identityGeneration, isCurrent = () => true) {
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
  });
  const body = await response.json();
  // Check before CSRF, errors, or callers can publish an obsolete response.
  if (epoch !== identityGeneration || !isCurrent()) throw new StaleResponse();
  if (!response.ok) throw new Error(body.error?.message || '请求失败，请重试。');
  if (body.data?.csrf_token) csrfToken = body.data.csrf_token;
  return body.data;
}

function renderList(id, values, format) {
  element(id).replaceChildren(...values.map(value => {
    const item = document.createElement('li');
    item.textContent = format(value);
    return item;
  }));
}

async function refreshNotes(epoch) {
  const notes = await api('/persistence-notes', {}, epoch);
  renderList('notes', notes, note => `${note.content} · ${new Date(note.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`);
  if (!notes.length) element('notes').textContent = '还没有验证记录。';
}

async function refresh(epoch) {
  try {
    clearLoadedData();
    const data = await api('/auth/session', {}, epoch);
    const nextKey = data.user ? `${data.user.id}:${data.user.role}` : '';
    if (identityKey !== nextKey || !data.user) clearPrivateState();
    identityKey = nextKey;
    element('loading').hidden = true;
    element('login-view').hidden = Boolean(data.user);
    element('dashboard').hidden = !data.user;
    if (!data.user) return;
    element('welcome').textContent = `你好，${data.user.display_name}`;
    element('identity').textContent = `${data.user.username} · ${data.user.role === 'admin' ? '管理员' : '学生'} · 已连接服务端`;
    element('admin').hidden = data.user.role !== 'admin';
    element('student-booking').hidden = data.user.role !== 'student';
    element('reservations').textContent = '预约尚未加载。';
    element('notes').textContent = '记录尚未加载。';
    const [rooms, rules] = await Promise.all([api('/rooms', {}, epoch), api('/rules', {}, epoch), refreshNotes(epoch), data.user.role === 'student' ? refreshReservations(epoch).catch(error => {
      // A newer list read must not cancel this identity's room/rule initialization.
      if (!(error instanceof StaleResponse)) throw error;
    }) : Promise.resolve()]);
    if (epoch !== identityGeneration) throw new StaleResponse();
    element('rules').textContent = `规则 v${rules.version}：单次最长 ${rules.settings.max_duration_minutes / 60} 小时，最多提前 ${rules.settings.max_advance_days} 天。当前为项目演示参数。`;
    element('rooms').replaceChildren(...rooms.map(room => {
      const card = document.createElement('div');
      card.className = 'room';
      card.textContent = room.name;
      const detail = document.createElement('span');
      detail.textContent = `${room.location} · ${room.seat_count} 个座位（资源目录）`;
      card.append(detail);
      return card;
    }));
    element('room-id').replaceChildren(...rooms.map(room => {
      const option = document.createElement('option');
      option.value = room.id;
      option.textContent = `${room.name}${room.enabled ? '' : '（停用）'}`;
      option.disabled = !room.enabled;
      return option;
    }));
    if (!element('start-at').value) {
      const tomorrow = new Date(Date.now() + 86400000).toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' });
      element('start-at').value = `${tomorrow}T09:00`;
      element('end-at').value = `${tomorrow}T10:00`;
    }
    element('admin').hidden = data.user.role !== 'admin';
    if (data.user.role === 'admin') {
      await refreshAdmin(epoch);
    }
    element('search-fields').disabled = data.user.role !== 'student';
    element('initialization-state').textContent = '';
    element('reload-admin').disabled = data.user.role !== 'admin';
  } catch (error) {
    if (epoch === identityGeneration && !(error instanceof StaleResponse)) {
      element('initialization-state').textContent = '工作台加载失败，请重新加载工作台。';
      element('reload-dashboard').hidden = false;
    }
    throw error;
  }
}

async function act(button, task, authChange = false, isCurrent = () => true) {
  const epoch = authChange ? ++identityGeneration : identityGeneration;
  if (authChange) {
    clearPrivateState();
    element('dashboard').hidden = true;
    // Serialize authentication writes so browser Set-Cookie headers cannot race.
    element('login-view').hidden = true;
    for (const control of document.querySelectorAll('button')) {
      control.disabled = false;
      busyButtons.delete(control);
    }
  }
  const operation = Symbol();
  busyButtons.set(button, operation);
  button.disabled = true;
  element('status').textContent = '';
  try { await task(epoch); } catch (error) {
    if (epoch === identityGeneration && isCurrent() && !(error instanceof StaleResponse)) {
      element('status').textContent = error.message;
      if (authChange && element('dashboard').hidden) element('login-view').hidden = false;
    }
  } finally {
    if (busyButtons.get(button) === operation) {
      busyButtons.delete(button);
      button.disabled = false;
    }
  }
}

element('login-form').addEventListener('submit', event => {
  event.preventDefault();
  const credentials = { username: element('username').value.trim(), password: element('password').value };
  act(event.submitter, async epoch => {
    await api('/auth/login', { method: 'POST', body: JSON.stringify(credentials) }, epoch);
    element('password').value = '';
    await refresh(epoch);
  }, true);
});
element('logout').addEventListener('click', event => {
  if (adminDirty && !confirm('规则修改尚未保存，确认退出并放弃修改？')) return;
  act(event.currentTarget, async epoch => {
  await api('/auth/logout', { method: 'POST' }, epoch);
  element('username').value = '';
  await refresh(epoch);
}, true);
});
element('note-form').addEventListener('submit', event => {
  event.preventDefault();
  if (adminDirty && !confirm('保存验证文本会重新加载工作台，确认放弃未保存的规则修改？')) return;
  const content = element('note').value;
  act(event.submitter, async epoch => {
    await api('/persistence-notes', { method: 'POST', body: JSON.stringify({ content }) }, epoch);
    element('note').value = '';
    await refresh(epoch);
    if (epoch !== identityGeneration) throw new StaleResponse();
    element('status').textContent = '已保存，可刷新页面验证。';
  });
});
const statusLabels = { PENDING_CHECKIN: '待签到', CANCELLED: '已取消', IN_USE: '使用中', ON_LEAVE: '暂离中', COMPLETED: '已结束', EXPIRED: '已超时' };
const beijingTime = value => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });

function reservationListCurrent(epoch, version) {
  return epoch === identityGeneration && version === reservationListGeneration;
}

async function refreshReservations(epoch, version = ++reservationListGeneration) {
  const isCurrent = () => reservationListCurrent(epoch, version);
  const button = element('reload-reservations');
  const operation = Symbol();
  // All list loads own this button, including loads after create/cancel.
  busyButtons.set(button, operation);
  button.disabled = true;
  try {
    const records = await api('/reservations', {}, epoch, isCurrent);
    if (!isCurrent()) throw new StaleResponse();
    element('reservations').replaceChildren(...records.map(record => {
      const item = document.createElement('li');
      item.dataset.reservationId = record.id;
      item.textContent = `${record.room_name} · ${record.seat_label} · ${beijingTime(record.start_at)} — ${beijingTime(record.end_at)}（北京时间）· ${statusLabels[record.status]} · 规则 v${record.rule_version_id}`;
      const actions = record.status === 'PENDING_CHECKIN' ? [['cancel', '取消预约'], ['check-in', '签到（页面确认）']]
        : record.status === 'IN_USE' ? [['leave', '暂离'], ['finish', '结束使用']]
          : record.status === 'ON_LEAVE' ? [['return', '返回座位'], ['finish', '结束使用']] : [];
      if (record.leave_deadline && record.status === 'ON_LEAVE') {
        const detail = document.createElement('p');
        detail.textContent = `暂离截止：${beijingTime(record.leave_deadline)}（北京时间）`;
        item.append(detail);
      }
      for (const [action, label] of actions) {
        const button = document.createElement('button');
        button.className = 'secondary';
        button.textContent = label;
        const key = crypto.randomUUID();
        button.addEventListener('click', () => {
          let listVersion;
          act(button, async current => {
            await api(`/reservations/${encodeURIComponent(record.id)}/${action}`, {
              method: 'POST', body: JSON.stringify({ idempotency_key: key }),
            }, current);
            listVersion = ++reservationListGeneration;
            invalidateSeats();
            element('status').textContent = `${label}已保存。`;
            try {
              const isCurrent = await refreshReservations(current, listVersion);
              if (isCurrent()) element('status').textContent = action === 'cancel' ? '已取消，对应时段已释放。' : `${label}已保存，可刷新查看。`;
            } catch (error) {
              if (!reservationListCurrent(current, listVersion)) throw new StaleResponse();
              element('status').textContent = `${label}已保存，列表刷新失败：${error.message} 请点击刷新预约。`;
            }
          }, false, () => listVersion === undefined || listVersion === reservationListGeneration);
        });
        item.append(button);
      }
      return item;
    }));
    if (!records.length) element('reservations').textContent = '还没有预约，请选择房间和时间查询。';
    return isCurrent;
  } catch (error) {
    // Network/JSON failures can occur before api checks its response guard.
    if (!isCurrent()) throw new StaleResponse();
    throw error;
  } finally {
    if (busyButtons.get(button) === operation) {
      busyButtons.delete(button);
      button.disabled = false;
    }
  }
}

function invalidateSeats(releaseButton = true) {
  ++seatQueryGeneration;
  if (releaseButton) {
    const button = element('search-form').querySelector('button');
    busyButtons.delete(button);
    button.disabled = false;
  }
  element('seat-id').replaceChildren();
  element('booking-form').hidden = true;
  element('availability').textContent = '请重新查询。';
}

function searchParameters() {
  // datetime-local has no timezone: append Beijing's explicit offset, never the device timezone.
  const value = id => `${element(id).value}:00+08:00`;
  return { room_id: element('room-id').value, start_at: value('start-at'), end_at: value('end-at') };
}

for (const id of ['room-id', 'start-at', 'end-at']) element(id).addEventListener('input', () => {
  invalidateSeats();
});
element('search-form').addEventListener('submit', event => {
  event.preventDefault();
  const parameters = searchParameters();
  act(event.submitter, async epoch => {
    invalidateSeats(false);
    const queryEpoch = seatQueryGeneration;
    element('availability').textContent = '正在查询…';
    try {
      const result = await api(`/seats?${new URLSearchParams(parameters)}`, {}, epoch, () => queryEpoch === seatQueryGeneration);
      element('seat-id').replaceChildren(...result.seats.map(seat => {
        const option = document.createElement('option');
        option.value = seat.id;
        option.textContent = seat.label;
        return option;
      }));
      element('availability').textContent = result.seats.length ? `此时段可预约 ${result.seats.length} 个座位。` : '没有可预约座位，或本人已有重叠预约。请调整时间或房间。';
      element('booking-form').hidden = result.seats.length === 0;
    } catch (error) {
      if (epoch !== identityGeneration || queryEpoch !== seatQueryGeneration) throw new StaleResponse();
      element('availability').textContent = '查询失败，请重试。';
      throw error;
    }
  });
});
element('booking-form').addEventListener('submit', event => {
  event.preventDefault();
  const { start_at, end_at } = searchParameters();
  const draft = { seat_id: element('seat-id').value, start_at, end_at };
  const fingerprint = JSON.stringify(draft);
  if (pendingBooking?.fingerprint !== fingerprint) pendingBooking = { fingerprint, ...draft, idempotency_key: crypto.randomUUID() };
  const { fingerprint: ignored, ...body } = pendingBooking;
  let listVersion;
  act(event.submitter, async epoch => {
    await api('/reservations', { method: 'POST', body: JSON.stringify(body) }, epoch);
    // Committed mutations invalidate every pre-operation list read before reloading.
    listVersion = ++reservationListGeneration;
    pendingBooking = null;
    invalidateSeats();
    element('status').textContent = '预约已保存。';
    try {
      const isCurrent = await refreshReservations(epoch, listVersion);
      if (!isCurrent()) return;
    } catch (error) {
      if (reservationListCurrent(epoch, listVersion)) element('status').textContent = `预约已保存，列表刷新失败：${error.message} 请点击刷新预约。`;
      return;
    }
    element('status').textContent = '预约已保存，可刷新页面或重新登录查看。';
  }, false, () => listVersion === undefined || listVersion === reservationListGeneration);
});
element('reload-reservations').addEventListener('click', event => {
  const version = ++reservationListGeneration;
  act(event.currentTarget, async epoch => {
    // Keep confirmed records/actions visible while the replacement is loading.
    element('status').textContent = '正在加载预约…';
    try {
      const isCurrent = await refreshReservations(epoch, version);
      if (isCurrent()) element('status').textContent = '';
    } catch (error) {
      if (!reservationListCurrent(epoch, version)) throw new StaleResponse();
      element('reservations').textContent = '预约加载失败，请重试。';
      throw error;
    }
  }, false, () => version === reservationListGeneration);
});
element('reload-dashboard').addEventListener('click', event => act(event.currentTarget, epoch => refresh(epoch)));
let adminGeneration = 0;
let previewGeneration = 0;
let adminDirty = false;
let adminRulesVersion = 0;
let ruleDraftGeneration = 0;
let adminRooms = [];
let adminSeats = [];
let closurePreview = null;
const ruleFields = { max_duration_minutes: 'rule-duration', max_advance_days: 'rule-advance', check_in_early_minutes: 'rule-early', check_in_late_minutes: 'rule-late', leave_limit_minutes: 'rule-leave' };
const adminPending = new Map();

function invalidatePreview() {
  ++previewGeneration;
  closurePreview = null;
  element('confirm-closure').hidden = true;
  element('closure-preview').textContent = '';
}
function clearAdminState() {
  ++adminGeneration;
  adminDirty = false;
  adminRulesVersion = 0;
  adminRooms = [];
  adminSeats = [];
  adminPending.clear();
  invalidatePreview();
  element('admin-fields').disabled = true;
  element('reload-admin').disabled = true;
  for (const id of ['admin-reservations', 'closures', 'closure-room', 'closure-seat', 'hours-room', 'rule-version']) element(id).replaceChildren();
  for (const id of [...Object.values(ruleFields), 'closure-reason', 'hours-open', 'hours-close']) element(id).value = '';
}
function options(id, values, label) {
  const previous = element(id).value;
  element(id).replaceChildren(...values.map(value => {
    const option = document.createElement('option');
    option.value = value.id;
    option.textContent = label(value);
    return option;
  }));
  if (values.some(value => value.id === previous)) element(id).value = previous;
}
function updateClosureSeats() {
  const room = element('closure-room').value;
  options('closure-seat', adminSeats.filter(seat => seat.room_id === room), seat => `${seat.label}${seat.enabled ? '' : '（停用）'}`);
  element('closure-seat').disabled = element('closure-scope').value === 'room';
}
const timeLabel = minutes => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
const timeMinutes = value => { const [hours, minutes] = value.split(':').map(Number); return hours * 60 + minutes; };
function updateHours() {
  const room = adminRooms.find(room => room.id === element('hours-room').value);
  if (!room) return;
  element('hours-open').value = timeLabel(room.opens_minute);
  element('hours-close').value = timeLabel(room.closes_minute);
}
async function refreshAdmin(epoch) {
  const version = ++adminGeneration;
  const current = () => epoch === identityGeneration && version === adminGeneration;
  try {
    const [records, resources, rules, events, rooms] = await Promise.all([
      api('/admin/reservations', {}, epoch, current), api('/admin/resources', {}, epoch, current),
      api('/rules', {}, epoch, current), api('/admin/audit-events', {}, epoch, current), api('/rooms', {}, epoch, current),
    ]);
    if (!current()) throw new StaleResponse();
    element('rules').textContent = `规则 v${rules.version}：单次最长 ${rules.settings.max_duration_minutes / 60} 小时，最多提前 ${rules.settings.max_advance_days} 天。当前为项目演示参数。`;
    adminRooms = rooms;
    adminSeats = resources.seats;
    renderList('admin-reservations', records, record => `${record.student_id} · ${record.room_name} ${record.seat_label} · ${beijingTime(record.start_at)} — ${beijingTime(record.end_at)} · ${statusLabels[record.status]} · ${record.id}`);
    if (!records.length) element('admin-reservations').textContent = '暂无预约记录。';
    if (!adminDirty) {
      adminRulesVersion = rules.version;
      for (const [key, id] of Object.entries(ruleFields)) element(id).value = rules.settings[key];
      element('rule-version').textContent = `当前规则 v${rules.version}；新规则仅用于新预约。`;
    } else {
      element('rule-version').textContent = `草稿基于 v${adminRulesVersion}，服务端当前 v${rules.version}；页面修改尚未保存。`;
    }
    options('closure-room', rooms, room => room.name);
    options('hours-room', rooms, room => room.name);
    updateClosureSeats();
    updateHours();
    element('closures').replaceChildren(...resources.closures.map(record => {
      const item = document.createElement('li');
      item.textContent = `${record.room_id || record.seat_id} · ${record.reason} · ${record.reopened_at ? '已重新开放' : '关闭中'} · ${record.id}`;
      if (!record.reopened_at) {
        const button = document.createElement('button');
        button.className = 'secondary';
        button.textContent = '重新开放';
        button.addEventListener('click', () => act(button, async current => {
          await adminWrite(`/admin/closures/${encodeURIComponent(record.id)}/reopen`, {}, current);
          invalidatePreview();
          await refreshAdmin(current);
          element('status').textContent = '已重新开放，已取消预约不会恢复。';
        }));
        item.append(button);
      }
      return item;
    }));
    if (!resources.closures.length) element('closures').textContent = '暂无关闭记录。';
    const eventLabels = { LOGIN: '登录', PERSISTENCE_NOTE_CREATED: '保存验证文本', RESERVATION_CREATED: '创建预约', RESERVATION_CANCELLED: '取消预约', CHECKED_IN: '签到', LEFT_SEAT: '暂离', RETURNED: '返回座位', RESERVATION_FINISHED: '结束使用', CHECKIN_EXPIRED: '未签到超时', LEAVE_EXPIRED: '暂离超时', RESERVATION_COMPLETED: '自然结束', RULES_UPDATED: '更新规则', ROOM_HOURS_UPDATED: '修改开放时间', RESOURCE_CLOSED: '关闭资源', RESOURCE_REOPENED: '重新开放资源', RESERVATION_CANCELLED_BY_CLOSURE: '资源关闭取消预约' };
    renderList('events', events, event => {
      const details = JSON.parse(event.details_json || '{}');
      const target = event.reservation_id ? `预约 ${event.reservation_id}` : event.action === 'RULES_UPDATED' ? `规则 v${event.target_id}` : event.target_id || '';
      const hours = event.action === 'ROOM_HOURS_UPDATED' ? ` · ${timeLabel(details.opens_minute)}—${timeLabel(details.closes_minute)}（北京时间）` : '';
      return `${eventLabels[event.action] || '其他操作'} · ${event.actor_id || '超时任务'} · ${beijingTime(event.occurred_at)} · ${target}${details.reason ? ' · ' + details.reason : ''}${hours} · 成功`;
    });
    [...element('events').children].forEach((item, index) => { item.dataset.action = events[index].action; });
    element('admin-fields').disabled = false;
    return current;
  } catch (error) {
    if (!current()) throw new StaleResponse();
    throw error;
  }
}
async function adminWrite(path, body, epoch) {
  const fingerprint = JSON.stringify([path, body]);
  if (!adminPending.has(fingerprint)) adminPending.set(fingerprint, crypto.randomUUID());
  const result = await api(path, { method: 'POST', body: JSON.stringify({ ...body, idempotency_key: adminPending.get(fingerprint) }) }, epoch);
  adminPending.delete(fingerprint);
  ++adminGeneration; // Committed writes invalidate all older management reads.
  return result;
}
element('rules-form').addEventListener('input', () => { adminDirty = true; ++ruleDraftGeneration; });
window.addEventListener('beforeunload', event => { if (adminDirty) { event.preventDefault(); event.returnValue = ''; } });
element('rules-form').addEventListener('submit', event => {
  event.preventDefault();
  const settings = Object.fromEntries(Object.entries(ruleFields).map(([key, id]) => [key, Number(element(id).value)]));
  const body = { settings, base_version: adminRulesVersion };
  const draftVersion = ruleDraftGeneration;
  act(event.submitter, async epoch => {
    const saved = await adminWrite('/admin/rules', body, epoch);
    adminRulesVersion = saved.version;
    if (draftVersion === ruleDraftGeneration) adminDirty = false;
    await refreshAdmin(epoch);
    element('status').textContent = adminDirty ? '提交的规则已保存；页面上后续修改仍未保存。' : '规则已保存；已有预约保留原规则。';
  });
});
element('discard-rules').addEventListener('click', event => act(event.currentTarget, async epoch => {
  if (adminDirty && !confirm('确认放弃未保存的规则修改？')) return;
  adminDirty = false;
  await refreshAdmin(epoch);
}));
element('hours-room').addEventListener('change', updateHours);
element('hours-form').addEventListener('submit', event => {
  event.preventDefault();
  const room = adminRooms.find(room => room.id === element('hours-room').value);
  const body = { opens_minute: timeMinutes(element('hours-open').value), closes_minute: timeMinutes(element('hours-close').value), base_hours: [room.opens_minute, room.closes_minute] };
  act(event.submitter, async epoch => {
    await adminWrite(`/admin/rooms/${encodeURIComponent(room.id)}/hours`, body, epoch);
    invalidatePreview();
    await refreshAdmin(epoch);
    element('status').textContent = '开放时间已保存。';
  });
});
for (const id of ['closure-room', 'closure-scope', 'closure-seat', 'closure-reason']) element(id).addEventListener('input', () => {
  invalidatePreview();
  if (id === 'closure-room' || id === 'closure-scope') updateClosureSeats();
});
element('closure-form').addEventListener('submit', event => {
  event.preventDefault();
  invalidatePreview();
  const version = previewGeneration;
  const body = { reason: element('closure-reason').value, ...(element('closure-scope').value === 'room' ? { room_id: element('closure-room').value } : { seat_id: element('closure-seat').value }) };
  act(event.submitter, async epoch => {
    closurePreview = await api('/admin/closures/preview', { method: 'POST', body: JSON.stringify(body) }, epoch, () => version === previewGeneration);
    const summary = document.createElement('p');
    summary.textContent = `将取消 ${closurePreview.affected.length} 条待签到预约；${closurePreview.blockers.length} 条使用中或暂离中预约阻止关闭。立即关闭，持续到重新开放。原因：${closurePreview.target.reason}`;
    const affected = document.createElement('ul');
    for (const record of [...closurePreview.affected, ...closurePreview.blockers]) {
      const item = document.createElement('li');
      item.textContent = `${record.status === 'PENDING_CHECKIN' ? '将取消' : '阻止关闭'} · ${record.student_id} · ${record.room_name} ${record.seat_label} · ${beijingTime(record.start_at)}—${beijingTime(record.end_at)}（北京时间）· ${record.id}`;
      affected.append(item);
    }
    element('closure-preview').replaceChildren(summary, affected);
    element('confirm-closure').hidden = closurePreview.blockers.length > 0;
  }, false, () => version === previewGeneration);
});
element('confirm-closure').addEventListener('click', event => {
  if (!closurePreview) return;
  const body = { preview_token: closurePreview.preview_token };
  act(event.currentTarget, async epoch => {
    await adminWrite('/admin/closures', body, epoch);
    invalidatePreview();
    await refreshAdmin(epoch);
    element('status').textContent = '资源已关闭，关联待签到预约已取消。';
  });
});
element('reload-admin').addEventListener('click', event => act(event.currentTarget, async epoch => {
  invalidatePreview();
  await refreshAdmin(epoch);
}));
const bootstrap = ++identityGeneration;
refresh(bootstrap).catch(error => {
  if (bootstrap !== identityGeneration || error instanceof StaleResponse) return;
  element('loading').hidden = true;
  element('status').textContent = `${error.message} 请确认服务已初始化，然后刷新页面。`;
});
