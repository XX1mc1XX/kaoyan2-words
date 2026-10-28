# -*- coding: utf-8 -*-
"""登录入口改成圆形头像（默认自绘 logo）；词族与词形合并一行、去掉「词族」二字。"""
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


# ---------- 头像 ----------
rep('<button class="account-btn" id="accountBtn">登录</button>',
    '''<button class="account-btn" id="accountBtn" aria-label="账号">
    <span class="avatar" id="accountAvatar"></span>
  </button>''', "头像按钮")

rep('''.account-btn{border:1px solid var(--line);background:transparent;color:var(--muted);
  font:inherit;font-size:12.5px;font-weight:700;border-radius:999px;padding:6px 11px;cursor:pointer;
  max-width:88px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.account-btn.online{color:var(--brand);border-color:color-mix(in srgb,var(--brand) 45%,var(--line))}''',
    '''.account-btn{border:0;background:none;padding:0;cursor:pointer;flex-shrink:0;line-height:0;
  border-radius:50%}
.account-btn:active{transform:scale(.94)}
.account-btn .avatar{display:flex;align-items:center;justify-content:center;width:34px;height:34px;
  border-radius:50%;overflow:hidden;background:var(--line);color:#fff;font-size:15px;font-weight:800;
  letter-spacing:0}
.account-btn .avatar svg{display:block;width:34px;height:34px}
.account-btn.online .avatar{background:linear-gradient(135deg,#f1b25b,#b45309)}
.account-btn.online .avatar svg{display:none}''', "头像样式")

# logo 定义 + 渲染
rep("let authUser = null;          // 登录状态要早于 save() 声明，否则初始化时会踩暂时性死区",
    '''// 自绘 logo：渐变圆 + 抽象「W」笔画
const AVATAR_LOGO = '<svg viewBox="0 0 36 36" aria-hidden="true">'
  + '<defs><linearGradient id="kyAv" x1="0" y1="0" x2="1" y2="1">'
  + '<stop offset="0" stop-color="#2dd4bf"/><stop offset="1" stop-color="#0f766e"/>'
  + '</linearGradient></defs>'
  + '<circle cx="18" cy="18" r="18" fill="url(#kyAv)"/>'
  + '<path d="M9.5 12.5l3.2 11 3.6-8.2 3.6 8.2 3.2-11" fill="none" stroke="#fff" '
  + 'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'
  + '</svg>';
let authUser = null;          // 登录状态要早于 save() 声明，否则初始化时会踩暂时性死区''', "logo 定义")

rep('''function renderAuth() {
  const btn = $('accountBtn');
  btn.textContent = authUser ? authUser : '登录';
  btn.classList.toggle('online', !!authUser);''',
    '''function renderAuth() {
  const btn = $('accountBtn');
  const avatar = $('accountAvatar');
  if (authUser) {
    avatar.textContent = authUser.slice(0, 1).toUpperCase();
    avatar.title = authUser;
  } else {
    avatar.textContent = '';
    avatar.insertAdjacentHTML('afterbegin', AVATAR_LOGO);
    avatar.title = '未登录，点这里登录或注册';
  }
  btn.classList.toggle('online', !!authUser);''', "头像渲染")

# ---------- 词族与词形合并一行 ----------
rep('''  const family = word.family || '';
  $('familyNote').textContent = family ? '词族：' + family : '';
  $('familyNote').classList.toggle('hidden', !family);
  const forms = Array.isArray(word.forms) ? word.forms.filter(Boolean) : [];
  $('forms').textContent = forms.join(' / ');
  $('formsBox').classList.toggle('hidden', forms.length === 0);''',
    '''  // 词族母词和词形变化放同一行，用「/」分隔，不再单独标「词族：」
  const family = word.family || '';
  const forms = Array.isArray(word.forms) ? word.forms.filter(Boolean) : [];
  const line = (family ? [family] : []).concat(forms);
  $('familyNote').classList.add('hidden');
  $('forms').textContent = line.join(' / ');
  $('formsBox').classList.toggle('hidden', line.length === 0);''', "词族并入词形行")

io.open(P, "w", encoding="utf-8", newline="\n").write(t)
print("\n".join(log))
