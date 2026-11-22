/* API transport, rendering, and event handlers keep server decisions authoritative. */
let csrfToken = '';
const element = id => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, {
    credentials: 'same-origin',
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
  });
  const body = await response.json();
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

async function refreshNotes() {
  const notes = await api('/persistence-notes');
  renderList('notes', notes, note => `${note.content} · ${new Date(note.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`);
  if (!notes.length) element('notes').textContent = '还没有验证记录。';
}

async function refresh() {
  const data = await api('/auth/session');
  element('loading').hidden = true;
  element('login-view').hidden = Boolean(data.user);
  element('dashboard').hidden = !data.user;
  if (!data.user) return;
  element('welcome').textContent = `你好，${data.user.display_name}`;
  element('identity').textContent = `${data.user.username} · ${data.user.role === 'admin' ? '管理员' : '学生'} · 已连接服务端`;
  const [rooms, rules] = await Promise.all([api('/rooms'), api('/rules'), refreshNotes()]);
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
    renderList('events', await api('/admin/audit-events'), event => `${event.action} · ${event.actor_id} · ${new Date(event.occurred_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`);
  }
}

async function act(button, task) {
  button.disabled = true;
  element('status').textContent = '';
  try { await task(); } catch (error) { element('status').textContent = error.message; }
  finally { button.disabled = false; }
}

element('login-form').addEventListener('submit', event => {
  event.preventDefault();
  act(event.submitter, async () => {
    await api('/auth/login', { method: 'POST', body: JSON.stringify({ username: element('username').value.trim(), password: element('password').value }) });
    element('password').value = '';
    await refresh();
  });
});
element('logout').addEventListener('click', event => act(event.currentTarget, async () => {
  await api('/auth/logout', { method: 'POST' });
  await refresh();
}));
element('note-form').addEventListener('submit', event => {
  event.preventDefault();
  act(event.submitter, async () => {
    await api('/persistence-notes', { method: 'POST', body: JSON.stringify({ content: element('note').value }) });
    element('note').value = '';
    await refresh();
    element('status').textContent = '已保存，可刷新页面验证。';
  });
});
refresh().catch(error => { element('loading').hidden = true; element('status').textContent = `${error.message} 请确认服务已初始化，然后刷新页面。`; });
