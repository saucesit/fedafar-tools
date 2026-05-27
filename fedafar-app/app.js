let PRODUCTS    = [];
let cart        = JSON.parse(localStorage.getItem('fedafar_cart') || '[]');
let activeCategory = 'all';
let currentUser = null;  // { nombre, tipo_precio }

const BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:5001'
    : '';

lucide.createIcons();

// ── DOM ────────────────────────────────────────────────────────────────────────
const loginScreen     = document.getElementById('login-screen');
const appDiv          = document.getElementById('app');
const loginUsernameEl = document.getElementById('login-username');
const loginPasswordEl = document.getElementById('login-password');
const loginBtn        = document.getElementById('login-btn');
const loginError      = document.getElementById('login-error');
const logoutBtn       = document.getElementById('logout-btn');

const productGrid      = document.getElementById('product-grid');
const searchInput      = document.getElementById('product-search');
const cartBtn          = document.getElementById('cart-btn');
const closeCartBtn     = document.getElementById('close-cart');
const backToShopBtn    = document.getElementById('back-to-shop');
const cartModal        = document.getElementById('cart-modal');
const cartCount        = document.getElementById('cart-count');
const cartItemsContainer = document.getElementById('cart-items');
const totalPriceEl     = document.getElementById('total-price');
const sendOrderBtn     = document.getElementById('send-order');
const categoryPills    = document.querySelectorAll('.pill');

const cuentaBtn        = document.getElementById('cuenta-btn');
const cuentaModal      = document.getElementById('cuenta-modal');
const closeCuentaBtn   = document.getElementById('close-cuenta');
const cuentaBody       = document.getElementById('cuenta-body');
const cuentaSaldoTotal = document.getElementById('cuenta-saldo-total');

// ── Auth ───────────────────────────────────────────────────────────────────────

async function checkSession() {
    try {
        const res = await fetch(`${BASE_URL}/api/me`, { credentials: 'include' });
        if (res.ok) {
            const data = await res.json();
            if (data.authenticated) {
                currentUser = data;
                showApp();
                return;
            }
        }
    } catch (e) {}
    showLogin();
}

function showLogin() {
    loginScreen.classList.remove('hidden');
    appDiv.classList.add('hidden');
}

function showApp() {
    loginScreen.classList.add('hidden');
    appDiv.classList.remove('hidden');
    showPriceBadge();
    fetchProducts();
    lucide.createIcons();
}

loginBtn.addEventListener('click', doLogin);
loginPasswordEl.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
loginUsernameEl.addEventListener('keydown', e => { if (e.key === 'Enter') loginPasswordEl.focus(); });

async function doLogin() {
    const username = loginUsernameEl.value.trim();
    const password = loginPasswordEl.value;
    if (!username || !password) {
        showLoginError('Ingresá usuario y contraseña.');
        return;
    }

    loginBtn.disabled  = true;
    loginBtn.innerText = 'Ingresando...';

    try {
        const res  = await fetch(`${BASE_URL}/api/login`, {
            method:      'POST',
            credentials: 'include',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify({ username, password }),
        });
        const data = await res.json();

        if (res.ok && data.ok) {
            currentUser = data;
            loginError.classList.add('hidden');
            showApp();
        } else {
            showLoginError(data.error || 'Error al iniciar sesión.');
        }
    } catch (e) {
        showLoginError('No se pudo conectar con el servidor.');
    } finally {
        loginBtn.disabled  = false;
        loginBtn.innerText = 'Ingresar';
    }
}

function showLoginError(msg) {
    loginError.innerText = msg;
    loginError.classList.remove('hidden');
}

logoutBtn.addEventListener('click', async () => {
    await fetch(`${BASE_URL}/api/logout`, { method: 'POST', credentials: 'include' });
    currentUser = null;
    cart = [];
    localStorage.removeItem('fedafar_cart');
    showLogin();
});

// ── Badge de precio ────────────────────────────────────────────────────────────

function showPriceBadge() {
    const existing = document.getElementById('price-badge');
    if (existing) existing.remove();

    const tipo  = currentUser?.tipo_precio || 'contado';
    const badge = document.createElement('span');
    badge.id = 'price-badge';
    badge.innerText = tipo === 'cta-cte' ? 'Cta. Cte.' : 'Contado';
    badge.style.cssText = `
        background: ${tipo === 'cta-cte' ? '#7c3aed' : '#28a745'};
        color: white; font-size: 0.7rem; font-weight: 600;
        padding: 3px 10px; border-radius: 20px; letter-spacing: 0.5px;
        display: inline-block; margin-left: 6px;
    `;
    document.querySelector('.brand-text').appendChild(badge);
}

// ── Productos ──────────────────────────────────────────────────────────────────

function renderProducts(filter = '', category = 'all') {
    productGrid.innerHTML = '';
    const filtered = PRODUCTS.filter(p => {
        const matchesSearch = p.name.toLowerCase().includes(filter.toLowerCase()) ||
                              p.lab.toLowerCase().includes(filter.toLowerCase());
        const matchesCat = category === 'all' || p.category === category;
        return matchesSearch && matchesCat;
    });

    if (filtered.length === 0) {
        productGrid.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:40px 0;">Sin resultados.</p>';
        return;
    }

    filtered.forEach(product => {
        const card = document.createElement('div');
        card.className = 'product-card';
        const precioTexto = product.price === 0 ? 'Sin cargo' : `$ ${product.price.toLocaleString('es-AR')}`;
        const promoHtml   = product.promo ? `<p class="prod-promo">${product.promo}</p>` : '';
        card.innerHTML = `
            <div class="prod-info">
                <span class="prod-lab">${product.lab}</span>
                <h3>${product.name}</h3>
                <p class="prod-price ${product.price === 0 ? 'prod-price--gratis' : ''}">${precioTexto}</p>
                ${promoHtml}
            </div>
            <div class="prod-actions">
                <input type="number" id="qty-${product.id}" class="qty-input" value="1" min="1">
                <button class="add-btn" data-id="${product.id}">Añadir</button>
            </div>
        `;
        productGrid.appendChild(card);
    });

    lucide.createIcons();

    document.querySelectorAll('.add-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id       = parseInt(btn.dataset.id);
            const qtyInput = document.getElementById(`qty-${id}`);
            const qty      = Math.max(1, parseInt(qtyInput.value) || 1);
            qtyInput.value = qty;
            addToCart(id, qty);
        });
    });
}

async function fetchProducts() {
    productGrid.innerHTML = '<p style="text-align:center;width:100%;padding:40px 0;">Cargando catálogo...</p>';
    try {
        const tipo = currentUser?.tipo_precio || 'contado';
        const res  = await fetch(`${BASE_URL}/api/productos?tipo=${tipo}`, { credentials: 'include' });
        PRODUCTS   = await res.json();
        cart = cart.filter(item => PRODUCTS.find(p => p.id === item.id));
        cart = cart.map(item => {
            const fresh = PRODUCTS.find(p => p.id === item.id);
            return { ...fresh, qty: item.qty };
        });
        updateCart();
        renderProducts();
    } catch (error) {
        productGrid.innerHTML = '<p style="text-align:center;color:red;width:100%;padding:40px 0;">Error al conectar con el servidor.</p>';
    }
}

// ── Carrito ────────────────────────────────────────────────────────────────────

function addToCart(productId, qtyToAdd) {
    const product  = PRODUCTS.find(p => p.id === productId);
    const existing = cart.find(item => item.id === productId);
    if (existing) {
        existing.qty += qtyToAdd;
    } else {
        cart.push({ ...product, qty: qtyToAdd });
    }
    const btn = document.querySelector(`.add-btn[data-id="${productId}"]`);
    if (btn) {
        btn.innerText = '¡Agregado!';
        setTimeout(() => btn.innerText = 'Añadir', 1500);
    }
    updateCart();
}

function updateCart() {
    const totalQty = cart.reduce((sum, item) => sum + item.qty, 0);
    cartCount.innerText = totalQty;
    cartItemsContainer.innerHTML = '';
    let totalValue = 0;

    cart.forEach(item => {
        const subtotal = item.price * item.qty;
        totalValue += subtotal;
        const itemEl = document.createElement('div');
        itemEl.className = 'cart-item';
        itemEl.innerHTML = `
            <div class="cart-item-info">
                <h4>${item.name}</h4>
                <div class="cart-item-controls">
                    <button class="qty-btn minus-btn" data-id="${item.id}">-</button>
                    <span class="item-qty">${item.qty}</span>
                    <button class="qty-btn plus-btn" data-id="${item.id}">+</button>
                    <button class="remove-btn" data-id="${item.id}"><i data-lucide="trash-2"></i></button>
                </div>
            </div>
            <div class="cart-item-price">
                <small>$ ${item.price.toLocaleString('es-AR')} c/u</small>
                <span>$ ${subtotal.toLocaleString('es-AR')}</span>
            </div>
        `;
        cartItemsContainer.appendChild(itemEl);
    });

    totalPriceEl.innerText = `$ ${totalValue.toLocaleString('es-AR')}`;
    localStorage.setItem('fedafar_cart', JSON.stringify(cart));
    lucide.createIcons();

    document.querySelectorAll('.minus-btn').forEach(btn =>
        btn.addEventListener('click', () => updateItemQty(parseInt(btn.dataset.id), -1)));
    document.querySelectorAll('.plus-btn').forEach(btn =>
        btn.addEventListener('click', () => updateItemQty(parseInt(btn.dataset.id), 1)));
    document.querySelectorAll('.remove-btn').forEach(btn =>
        btn.addEventListener('click', () => removeItem(parseInt(btn.dataset.id))));
}

function updateItemQty(productId, change) {
    const existing = cart.find(item => item.id === productId);
    if (existing) {
        existing.qty += change;
        if (existing.qty <= 0) removeItem(productId);
        else updateCart();
    }
}

function removeItem(productId) {
    cart = cart.filter(item => item.id !== productId);
    updateCart();
}

// ── Mi Cuenta ──────────────────────────────────────────────────────────────────

cuentaBtn.addEventListener('click', () => {
    cuentaModal.classList.remove('hidden');
    loadCuentaCorriente();
});
closeCuentaBtn.addEventListener('click', () => cuentaModal.classList.add('hidden'));

const backFromCuentaBtn = document.getElementById('back-from-cuenta');
if (backFromCuentaBtn) backFromCuentaBtn.addEventListener('click', () => cuentaModal.classList.add('hidden'));

async function loadCuentaCorriente() {
    cuentaBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Cargando...</p>';
    cuentaSaldoTotal.innerText = '$ 0,00';

    try {
        const res  = await fetch(`${BASE_URL}/api/cta-cte`, { credentials: 'include' });
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
            cuentaBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Sin comprobantes pendientes 🎉</p>';
            return;
        }

        let totalSaldo = 0;
        let html = `
            <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:12px;">
                📋 Solo se muestran comprobantes con saldo pendiente.
            </p>
            <table class="cuenta-table">
                <thead>
                    <tr>
                        <th>Comprobante</th>
                        <th>Vencimiento</th>
                        <th>Saldo</th>
                    </tr>
                </thead>
                <tbody>
        `;
        data.forEach(row => {
            const saldo = parseFloat(row.saldo) || 0;
            totalSaldo += saldo;
            const vence = row.fecha_vencimiento ? row.fecha_vencimiento.substring(0, 10) : '-';
            const saldoClass = saldo > 0 ? 'saldo-pendiente' : 'saldo-ok';
            html += `
                <tr>
                    <td>${row.comprobante || '-'}</td>
                    <td>${vence}</td>
                    <td class="${saldoClass}">$ ${saldo.toLocaleString('es-AR', {minimumFractionDigits:2})}</td>
                </tr>
            `;
        });
        html += '</tbody></table>';

        cuentaBody.innerHTML = html;
        cuentaSaldoTotal.innerText = `$ ${totalSaldo.toLocaleString('es-AR', {minimumFractionDigits:2})}`;
        cuentaSaldoTotal.style.color = totalSaldo > 0 ? '#dc3545' : '#28a745';

    } catch (e) {
        cuentaBody.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar la cuenta.</p>';
    }
}

// ── Eventos ────────────────────────────────────────────────────────────────────

searchInput.addEventListener('input', (e) => renderProducts(e.target.value, activeCategory));

categoryPills.forEach(pill => {
    pill.addEventListener('click', () => {
        categoryPills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        activeCategory = pill.dataset.cat;
        renderProducts(searchInput.value, activeCategory);
    });
});

cartBtn.addEventListener('click',    () => cartModal.classList.remove('hidden'));
closeCartBtn.addEventListener('click', () => cartModal.classList.add('hidden'));
if (backToShopBtn) backToShopBtn.addEventListener('click', () => cartModal.classList.add('hidden'));

sendOrderBtn.addEventListener('click', () => {
    if (cart.length === 0) return alert('El carrito está vacío');
    const tipo  = currentUser?.tipo_precio || 'contado';
    const label = tipo === 'cta-cte' ? 'Cuenta Corriente' : 'Contado';
    let msg = `📦 *NUEVO PEDIDO - FEDAFAR*\n💳 Precio: ${label}\n`;
    if (currentUser?.nombre) msg += `🏪 Farmacia: ${currentUser.nombre}\n`;
    msg += '\n';
    cart.forEach(item => { msg += `• ${item.name} (${item.lab}) x${item.qty}\n`; });
    msg += `\n*TOTAL ESTIMADO:* ${totalPriceEl.innerText}`;
    msg += `\n\n_Por favor confirmar stock y precios vigentes._`;
    window.open(`https://wa.me/5493876835525?text=${encodeURIComponent(msg)}`);
});

// ── Init ───────────────────────────────────────────────────────────────────────
checkSession();
