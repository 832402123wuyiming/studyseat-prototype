/* API transport, rendering, and event handlers keep server decisions authoritative. */
let csrfToken = '';
// Identity transitions invalidate every private response; query edits invalidate seats only.
let identityGeneration = 0;
let seatQueryGeneration = 0;
let reservationListGeneration = 0;
let identityKey = '';
let pendingBooking = null;
let adminResources = { rooms: [], seats: [] };
let closurePreview = null;
const busyButtons = new WeakMap();
const element = id => document.getElementById(id);
class StaleResponse extends Error {}

function clearLoadedData() {
  ++reservationListGeneration;
  for (const id of ['rooms', 'rules', 'notes', 'events', 'reservations', 'seat-id', 'room-id', 'closures', 'closure-target']) element(id).replaceChildren();
  element('admin').hidden = true;
  element('student-booking').hidden = true;
  element('booking-form').hidden = true;
  element('closure-impact').hidden = true;
  element('closure-apply').disabled = true;
  closurePreview = null;
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

function setRuleInputs(settings) {
  element('rule-duration').value = settings.max_duration_minutes;
  element('rule-advance').value = settings.max_advance_days;
  element('rule-early').value = settings.check_in_early_minutes;
  element('rule-late').value = settings.check_in_late_minutes;
  element('rule-leave').value = settings.leave_limit_minutes;
}

function renderClosureTargets() {
  const scope = element('closure-scope').value;
  const values = scope === 'room'
    ? adminResources.rooms.map(room => ({ id: room.id, label: room.name }))
    : adminResources.seats.map(seat => ({ id: seat.id, label: `${seat.room_id} · ${seat.label}` }));
  element('closure-target').replaceChildren(...values.map(value => {
    const option = document.createElement('option');
    option.value = value.id;
    option.textContent = value.label;
    return option;
  }));
  closurePreview = null;
  element('closure-apply').disabled = true;
  element('closure-impact').hidden = true;
}

function renderClosures(records) {
  element('closures').replaceChildren(...records.map(record => {
    const item = document.createElement('li');
    const scope = record.room_id ? `房间 ${record.room_name}` : `座位 ${record.seat_label}`;
    const reopened = record.reopened_at ? '已重开' : '关闭中';
    item.textContent = `${scope} · ${record.reason} · ${reopened} · ${beijingTime(record.created_at)}`;
    if (!record.reopened_at) {
      const button = document.createElement('button');
      button.className = 'secondary';
      button.textContent = '重新开放';
      button.addEventListener('click', () => act(button, async epoch => {
        await api(`/admin/closures/${encodeURIComponent(record.id)}/reopen`, { method: 'POST' }, epoch);
        element('status').textContent = '资源已重新开放，已取消的预约不会恢复。';
        await refresh(epoch);
      }));
      item.append(button);
    }
    return item;
  }));
  if (!records.length) element('closures').textContent = '还没有关闭记录。';
}

function closureBody() {
  const scope = element('closure-scope').value;
  const body = { reason: element('closure-reason').value.trim() };
  body[scope === 'room' ? 'room_id' : 'seat_id'] = element('closure-target').value;
  return body;
}

function renderClosureImpact(data) {
  const lines = [`预计取消 ${data.cancellable_count} 条待签到预约；${data.blocking_count} 条使用中或暂离中预约阻止关闭。`];
  for (const row of data.reservations) {
    lines.push(`${row.student_name} · ${row.seat_label} · ${beijingTime(row.start_at)} — ${beijingTime(row.end_at)} · ${statusLabels[row.status]}`);
  }
  element('closure-impact').textContent = lines.join('\n');
  element('closure-impact').hidden = false;
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
      setRuleInputs(rules.settings);
      const [resources, closures, events] = await Promise.all([
        api('/admin/resources', {}, epoch),
        api('/admin/closures', {}, epoch),
        api('/admin/audit-events', {}, epoch),
      ]);
      adminResources = resources;
      renderClosureTargets();
      renderClosures(closures);
      renderList('events', events, event => `${event.action} · ${event.actor_id} · ${new Date(event.occurred_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`);
    }
    element('search-fields').disabled = data.user.role !== 'student';
    element('initialization-state').textContent = '';
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
element('logout').addEventListener('click', event => act(event.currentTarget, async epoch => {
  await api('/auth/logout', { method: 'POST' }, epoch);
  element('username').value = '';
  await refresh(epoch);
}, true));
element('note-form').addEventListener('submit', event => {
  event.preventDefault();
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
      const leaveLimit = record.rule_snapshot.leave_limit_minutes;
      const actions = {
        PENDING_CHECKIN: [['cancel', '取消预约', '已取消，对应时段已释放。'], ['check-in', '签到', '已签到，开始计时。']],
        IN_USE: [['leave', '暂离', `已暂离，请在 ${leaveLimit} 分钟内返回。`], ['finish', '结束', '已结束使用。']],
        ON_LEAVE: [['return', '返回', '已返回座位。'], ['finish', '结束', '已结束使用。']],
      }[record.status] || [];
      const actionRow = document.createElement('div');
      actionRow.className = 'actions';
      for (const [path, label, done] of actions) {
        const button = document.createElement('button');
        button.className = 'secondary';
        button.textContent = label;
        button.addEventListener('click', () => {
          let listVersion;
          act(button, async current => {
            await api(`/reservations/${encodeURIComponent(record.id)}/${path}`, { method: 'POST' }, current);
            listVersion = ++reservationListGeneration;
            invalidateSeats();
            const isCurrent = await refreshReservations(current, listVersion);
            if (isCurrent()) element('status').textContent = done;
          }, false, () => listVersion === undefined || listVersion === reservationListGeneration);
        });
        actionRow.append(button);
      }
      if (actions.length) item.append(actionRow);
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
element('rules-form').addEventListener('submit', event => {
  event.preventDefault();
  const body = {
    max_duration_minutes: Number(element('rule-duration').value),
    max_advance_days: Number(element('rule-advance').value),
    check_in_early_minutes: Number(element('rule-early').value),
    check_in_late_minutes: Number(element('rule-late').value),
    leave_limit_minutes: Number(element('rule-leave').value),
  };
  act(event.submitter, async epoch => {
    const result = await api('/admin/rules', { method: 'POST', body: JSON.stringify(body) }, epoch);
    await refresh(epoch);
    if (epoch !== identityGeneration) throw new StaleResponse();
    element('status').textContent = `规则已保存为新版本 v${result.version}，已有预约保留原快照。`;
  });
});
element('closure-scope').addEventListener('change', renderClosureTargets);
element('closure-target').addEventListener('change', () => {
  closurePreview = null;
  element('closure-apply').disabled = true;
  element('closure-impact').hidden = true;
});
element('closure-preview').addEventListener('click', event => {
  const body = closureBody();
  act(event.currentTarget, async epoch => {
    const data = await api('/admin/closures/preview', { method: 'POST', body: JSON.stringify(body) }, epoch);
    closurePreview = { ...body, token: data.token };
    renderClosureImpact(data);
    element('closure-apply').disabled = !data.can_apply;
    element('status').textContent = data.can_apply
      ? '影响预览已生成，请确认关闭。'
      : '存在使用中或暂离中的预约，暂不能关闭。';
  });
});
element('closure-apply').addEventListener('click', async event => {
  if (!closurePreview) return;
  const button = event.currentTarget;
  const body = closurePreview;
  const epoch = identityGeneration;
  button.disabled = true;
  element('status').textContent = '';
  try {
    await api('/admin/closures', { method: 'POST', body: JSON.stringify(body) }, epoch);
    element('closure-reason').value = '';
    closurePreview = null;
    element('status').textContent = '资源已关闭，受影响的待签到预约已取消。';
    await refresh(epoch);
    button.disabled = true;
  } catch (error) {
    if (epoch === identityGeneration && !(error instanceof StaleResponse)) {
      element('status').textContent = error.message;
    }
    button.disabled = !closurePreview;
  }
});
const bootstrap = ++identityGeneration;
refresh(bootstrap).catch(error => {
  if (bootstrap !== identityGeneration || error instanceof StaleResponse) return;
  element('loading').hidden = true;
  element('status').textContent = `${error.message} 请确认服务已初始化，然后刷新页面。`;
});
