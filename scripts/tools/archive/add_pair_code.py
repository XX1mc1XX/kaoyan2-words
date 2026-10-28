# -*- coding: utf-8 -*-
"""登录面板加配对码：电脑生成 6 位码，手机输入即登录同一账号。"""
import io

P = r"c:\my_project\单词\software\template.html"
t = io.open(P, encoding="utf-8").read()
log = []


def rep(old, new, label):
    global t
    if old in t:
        t = t.replace(old, new, 1)
        log.append("OK    " + label)
    else:
        log.append("MISS  " + label)


# 1. HTML
rep('''    <button class="wx-btn" id="wxLogin" disabled title="需微信开放平台网站应用资质">微信扫码登录（暂不可用）</button>''',
    '''    <button class="wx-btn" id="wxLogin" disabled title="需微信开放平台网站应用资质">微信扫码登录（暂不可用）</button>
    <button class="auth-switch" id="pairClaimToggle">用配对码登录（在电脑上生成）</button>
    <div class="auth-pair hidden" id="pairClaimBox">
      <input class="auth-input" id="pairCode" inputmode="numeric" maxlength="6" placeholder="6 位配对码">
      <button class="btn" id="pairClaimBtn">登录</button>
    </div>
    <div class="auth-pair hidden" id="pairNewBox">
      <button class="btn" id="pairNewBtn">在另一台设备登录</button>
      <div class="pair-code hidden" id="pairCodeShow"></div>
    </div>''', "配对码 UI")

# 2. 样式
rep('.auth-sync{display:flex;flex-direction:column;gap:8px}',
    '''.auth-sync{display:flex;flex-direction:column;gap:8px}
.auth-pair{display:flex;flex-direction:column;gap:8px}
.pair-code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:30px;font-weight:800;
  letter-spacing:.18em;text-align:center;color:var(--brand);padding:10px 0}
.pair-tip{font-size:12px;color:var(--muted);text-align:center;line-height:1.5}''', "配对码样式")

# 3. 逻辑
rep('''$('syncUp').onclick = () => uploadProgress(false);''',
    '''$('pairClaimToggle').onclick = () => {
  $('pairClaimBox').classList.toggle('hidden');
};
$('pairClaimBtn').onclick = async () => {
  const code = $('pairCode').value.replace(/\\D/g, '');
  if (code.length !== 6) { authSay('配对码是 6 位数字', 'err'); return; }
  try {
    const r = await api('/pair/claim', { body: { code } });
    $('pairCode').value = '';
    $('pairClaimBox').classList.add('hidden');
    await afterLogin(r.username);
  } catch (e) {
    authSay(e.message, 'err');
  }
};
$('pairNewBtn').onclick = async () => {
  try {
    const r = await api('/pair/new', { method: 'POST' });
    const box = $('pairCodeShow');
    box.classList.remove('hidden');
    box.textContent = r.code;
    const mins = Math.max(1, Math.round((r.expiresAt - Date.now()) / 60000));
    authSay('在另一台设备输入这 6 位码，' + mins + ' 分钟内有效', 'ok');
  } catch (e) {
    authSay(e.message, 'err');
  }
};
$('syncUp').onclick = () => uploadProgress(false);''', "配对码逻辑")

# 4. 已登录时显示生成入口，未登录时显示输入入口
rep('''  $('authSync').classList.toggle('hidden', !authUser);''',
    '''  $('authSync').classList.toggle('hidden', !authUser);
  $('pairNewBox').classList.toggle('hidden', !authUser);
  $('pairClaimToggle').classList.toggle('hidden', !!authUser);
  if (authUser) $('pairClaimBox').classList.add('hidden');
  else $('pairCodeShow').classList.add('hidden');''', "配对码入口切换")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
