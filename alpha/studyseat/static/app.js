/* API transport, rendering, and event handlers keep server decisions authoritative. */
let csrfToken = '';
let generation = 0;
let identityKey = '';
const busyButtons = new WeakMap();
const element = id => document.getElementById(id);
class StaleResponse extends Error {}

function clearLoadedData() {
  for (const id of ['rooms', 'rules', 'notes', 'events']) element(id).replaceChildren();
  element('admin').hidden = true;
}

function clearPrivateState() {
  clearLoadedData();
  for (const id of ['welcome', 'identity']) element(id).textContent = '';
  for (const id of ['note', 'password']) element(id).value = '';
  identityKey = '';
}

async function api(path, options = {}, epoch = generation) {
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
  });
  const body = await response.json();
  // Check before CSRF, errors, or callers can publish an obsolete response.
  if (epoch !== generation) throw new StaleResponse();
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
  element('notes').textContent = '记录尚未加载。';
  const [rooms, rules] = await Promise.all([api('/rooms', {}, epoch), api('/rules', {}, epoch), refreshNotes(epoch)]);
  if (epoch !== generation) throw new StaleResponse();
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
  element('admin').hidden = data.user.role !== 'admin';
  if (data.user.role === 'admin') {
    renderList('events', await api('/admin/audit-events', {}, epoch), event => `${event.action} · ${event.actor_id} · ${new Date(event.occurred_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`);
  }
}

async function act(button, task, authChange = false) {
  const epoch = ++generation;
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
  busyButtons.set(button, epoch);
  button.disabled = true;
  element('status').textContent = '';
  try { await task(epoch); } catch (error) {
    if (epoch === generation && !(error instanceof StaleResponse)) {
      element('status').textContent = error.message;
      if (authChange && element('dashboard').hidden) element('login-view').hidden = false;
    }
  } finally {
    if (busyButtons.get(button) === epoch) {
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
    if (epoch !== generation) throw new StaleResponse();
    element('status').textContent = '已保存，可刷新页面验证。';
  });
});
const bootstrap = ++generation;
refresh(bootstrap).catch(error => {
  if (bootstrap !== generation || error instanceof StaleResponse) return;
  element('loading').hidden = true;
  element('status').textContent = `${error.message} 请确认服务已初始化，然后刷新页面。`;
});
