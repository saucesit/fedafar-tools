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

const todasCuentasBtn   = document.getElementById('todas-cuentas-btn');
const todasCuentasModal = document.getElementById('todas-cuentas-modal');
const closeTodasCuentas = document.getElementById('close-todas-cuentas');
const todasCuentasBody  = document.getElementById('todas-cuentas-body');
const adminPanelBtn     = document.getElementById('admin-panel-btn');

// Documentos
const docsBtn           = document.getElementById('docs-btn');
const docsModal         = document.getElementById('docs-modal');
const closeDocsBtn      = document.getElementById('close-docs');
const backFromDocs      = document.getElementById('back-from-docs');
const docsModalTitle    = document.getElementById('docs-modal-title');
const docsBody          = document.getElementById('docs-body');
const docsUploadSection = document.getElementById('docs-upload-section');
const docsEmpleadoSel   = document.getElementById('docs-empleado-sel');
const docsTipoSel       = document.getElementById('docs-tipo-sel');
const docsPeriodoInput  = document.getElementById('docs-periodo-input');
const docsFileInput     = document.getElementById('docs-file-input');
const docsFileName      = document.getElementById('docs-file-name');
const docsUploadBtn     = document.getElementById('docs-upload-btn');
const docsUploadMsg     = document.getElementById('docs-upload-msg');
// Faltantes
const faltantesBtn          = document.getElementById('faltantes-btn');
const faltantesModal        = document.getElementById('faltantes-modal');
const closeFaltantesBtn     = document.getElementById('close-faltantes');
const backFromFaltantesBtn  = document.getElementById('back-from-faltantes');
const faltantesBody         = document.getElementById('faltantes-body');
const faltantesFormSection  = document.getElementById('faltantes-form-section');
const faltanteProductoInput = document.getElementById('faltante-producto-input');
const faltanteNotaInput     = document.getElementById('faltante-nota-input');
const faltanteSubmitBtn     = document.getElementById('faltante-submit-btn');
const faltanteSubmitMsg     = document.getElementById('faltante-submit-msg');
const faltantesCount        = document.getElementById('faltantes-count');

// Firma
const firmaModal        = document.getElementById('firma-modal');
const closeFirmaBtn     = document.getElementById('close-firma');
const firmaDocNombre    = document.getElementById('firma-doc-nombre');
const firmaLimpiarBtn   = document.getElementById('firma-limpiar-btn');
const firmaConfirmarBtn = document.getElementById('firma-confirmar-btn');
const firmaMsgEl        = document.getElementById('firma-msg');

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

    const tipo = currentUser?.tipo_precio;

    // Carrito: visible para cliente, jefe, admin — oculto para empleado/farmaceutico/jefe_deposito
    if (tipo === 'empleado' || tipo === 'farmaceutico' || tipo === 'jefe_deposito') {
        cartBtn.classList.add('hidden');
    } else {
        cartBtn.classList.remove('hidden');
    }

    // Mi Cuenta (propia): cliente y admin
    if (tipo === 'cliente' || tipo === 'contado' || tipo === 'cta-cte' || tipo === 'admin') {
        cuentaBtn.classList.remove('hidden');
    } else {
        cuentaBtn.classList.add('hidden');
    }

    // Todas las Cuentas: jefe y admin
    if (tipo === 'jefe' || tipo === 'admin') {
        todasCuentasBtn.classList.remove('hidden');
    } else {
        todasCuentasBtn.classList.add('hidden');
    }

    // Panel Admin: solo admin
    if (tipo === 'admin') {
        adminPanelBtn.classList.remove('hidden');
        adminPanelBtn.onclick = async () => {
            await fetch(`${BASE_URL}/api/admin/auto-auth`, { method: 'POST', credentials: 'include' });
            window.open('/admin', '_blank');
        };
    } else {
        adminPanelBtn.classList.add('hidden');
    }

    // Documentos y préstamos: empleado, jefe, admin, farmaceutico, jefe_deposito
    if (tipo === 'empleado' || tipo === 'jefe' || tipo === 'admin' || tipo === 'farmaceutico' || tipo === 'jefe_deposito') {
        docsBtn.classList.remove('hidden');
        prestamosBtn.classList.remove('hidden');
        actualizarBadgePrestamos();
    } else {
        docsBtn.classList.add('hidden');
        prestamosBtn.classList.add('hidden');
    }

    // Faltantes: jefe_deposito, farmaceutico, jefe, admin
    if (tipo === 'jefe_deposito' || tipo === 'farmaceutico' || tipo === 'jefe' || tipo === 'admin') {
        faltantesBtn.classList.remove('hidden');
        actualizarBadgeFaltantes();
    } else {
        faltantesBtn.classList.add('hidden');
    }

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
    const labels = { 'cta-cte': 'Cta. Cte.', 'empleado': 'Empleado', 'contado': 'Contado', 'jefe': 'Jefe', 'admin': 'Admin', 'jefe_deposito': 'Jefe Depósito', 'farmaceutico': 'Farmacéutico' };
    const colors = { 'cta-cte': '#7c3aed', 'empleado': '#e07b00', 'contado': '#28a745', 'jefe': '#db2777', 'admin': '#dc2626', 'jefe_deposito': '#0369a1', 'farmaceutico': '#065f46' };
    badge.innerText = labels[tipo] || tipo;
    badge.style.cssText = `
        background: ${colors[tipo] || '#28a745'};
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
                              p.lab.toLowerCase().includes(filter.toLowerCase()) ||
                              (p.principio && p.principio.toLowerCase().includes(filter.toLowerCase()));
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
        const principioHtml = product.principio ? `<p class="prod-principio">${product.principio}</p>` : '';
        const promoHtml     = product.promo ? `<p class="prod-promo">${product.promo}</p>` : '';
        const tipo       = currentUser?.tipo_precio;
        const verDual    = tipo === 'empleado' || tipo === 'jefe' || tipo === 'admin' || tipo === 'farmaceutico' || tipo === 'jefe_deposito';
        const conCarrito = tipo !== 'empleado' && tipo !== 'farmaceutico' && tipo !== 'jefe_deposito';

        if (verDual && product.price_contado !== undefined) {
            const pc  = product.price_contado === 0 ? 'Sin cargo' : `$ ${product.price_contado.toLocaleString('es-AR')}`;
            const pcc = product.price_ctacte  === 0 ? 'Sin cargo' : `$ ${product.price_ctacte.toLocaleString('es-AR')}`;
            const cartHtml = conCarrito ? `
                <div class="prod-actions">
                    <input type="number" id="qty-${product.id}" class="qty-input" value="1" min="1">
                    <button class="add-btn" data-id="${product.id}">Añadir</button>
                </div>` : '';
            card.innerHTML = `
                <div class="prod-info prod-info--empleado">
                    <span class="prod-lab">${product.lab}</span>
                    <h3>${product.name}</h3>
                    ${principioHtml}
                    <div class="prod-precios-empleado">
                        <div class="prod-precio-item">
                            <span class="prod-precio-label">Contado</span>
                            <span class="prod-precio-valor">${pc}</span>
                        </div>
                        <div class="prod-precio-item prod-precio-item--ctacte">
                            <span class="prod-precio-label">Cta. Cte.</span>
                            <span class="prod-precio-valor">${pcc}</span>
                        </div>
                        ${(tipo === 'jefe' || tipo === 'admin') && product.stock !== undefined ? `
                        <div class="prod-precio-item prod-precio-item--stock">
                            <span class="prod-precio-label">Stock</span>
                            <span class="prod-precio-valor">${product.stock}</span>
                        </div>` : ''}
                    </div>
                    ${promoHtml}
                </div>
                ${cartHtml}
            `;
        } else {
            const precioTexto = product.price === 0 ? 'Sin cargo' : `$ ${product.price.toLocaleString('es-AR')}`;
            card.innerHTML = `
                <div class="prod-info">
                    <span class="prod-lab">${product.lab}</span>
                    <h3>${product.name}</h3>
                    ${principioHtml}
                    <p class="prod-price ${product.price === 0 ? 'prod-price--gratis' : ''}">${precioTexto}</p>
                    ${promoHtml}
                </div>
                <div class="prod-actions">
                    <input type="number" id="qty-${product.id}" class="qty-input" value="1" min="1">
                    <button class="add-btn" data-id="${product.id}">Añadir</button>
                </div>
            `;
        }
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

// ── Todas las Cuentas (Jefe / Admin) ──────────────────────────────────────────

if (todasCuentasBtn) todasCuentasBtn.addEventListener('click', () => {
    todasCuentasModal.classList.remove('hidden');
    loadTodasCuentas();
});
if (closeTodasCuentas) closeTodasCuentas.addEventListener('click', () => todasCuentasModal.classList.add('hidden'));
const backFromTodasCuentas = document.getElementById('back-from-todas-cuentas');
if (backFromTodasCuentas) backFromTodasCuentas.addEventListener('click', () => todasCuentasModal.classList.add('hidden'));

async function loadTodasCuentas() {
    todasCuentasBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Cargando...</p>';

    try {
        const res  = await fetch(`${BASE_URL}/api/todas-cuentas`, { credentials: 'include' });
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
            todasCuentasBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Sin datos.</p>';
            return;
        }

        let html = `
            <table class="cuenta-table">
                <thead>
                    <tr>
                        <th>Farmacia</th>
                        <th>Fact. pendientes</th>
                        <th>Saldo total</th>
                    </tr>
                </thead>
                <tbody>
        `;
        data.forEach(row => {
            const saldo = parseFloat(row.saldo_total) || 0;
            const saldoClass = saldo > 0 ? 'saldo-pendiente' : 'saldo-ok';
            const tieneComp = (row.comprobantes_pendientes || 0) > 0;
            const onclick = tieneComp
                ? `onclick="verComprobantesCliente(${row.genexus_client_id}, '${(row.nombre||'').replace(/'/g,"\\'")}')"`
                : '';
            html += `
                <tr class="${tieneComp ? 'cuenta-row-click' : ''}" ${onclick}>
                    <td><strong>${row.nombre}</strong>${tieneComp ? ' <span style="color:var(--text-muted);font-size:0.75rem;">›</span>' : ''}</td>
                    <td style="text-align:center">${row.comprobantes_pendientes}</td>
                    <td class="${saldoClass}">$ ${saldo.toLocaleString('es-AR', {minimumFractionDigits:2})}</td>
                </tr>
            `;
        });
        html += '</tbody></table>';
        html += '<p style="text-align:center;font-size:0.75rem;color:var(--text-muted);margin-top:10px;">Tocá una farmacia para ver sus comprobantes y descargar el PDF.</p>';
        todasCuentasBody.innerHTML = html;

    } catch (e) {
        todasCuentasBody.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar.</p>';
    }
}

async function verComprobantesCliente(gxId, nombre) {
    todasCuentasBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Cargando...</p>';
    try {
        const res  = await fetch(`${BASE_URL}/api/cliente/${gxId}/comprobantes`, { credentials: 'include' });
        const data = await res.json();
        const comps = data.comprobantes || [];

        let html = `<button class="secondary-btn" onclick="loadTodasCuentas()" style="margin-bottom:14px;">← Volver al listado</button>`;
        html += `<h3 style="color:var(--primary);margin:0 0 12px;">${data.nombre || nombre}</h3>`;

        if (comps.length === 0) {
            html += '<p style="text-align:center;padding:20px;color:var(--text-muted);">Sin comprobantes pendientes 🎉</p>';
        } else {
            html += `
                <table class="cuenta-table">
                    <thead>
                        <tr><th>Comprobante</th><th>Vence</th><th>Saldo</th><th style="text-align:center">PDF</th></tr>
                    </thead>
                    <tbody>`;
            comps.forEach(c => {
                const saldo = parseFloat(c.saldo) || 0;
                const comp  = (c.comprobante || '').replace(/'/g,"\\'");
                html += `
                    <tr>
                        <td>${c.comprobante || ''}</td>
                        <td>${(c.fecha_vencimiento || '').substring(0,10)}</td>
                        <td class="saldo-pendiente">$ ${saldo.toLocaleString('es-AR', {minimumFractionDigits:2})}</td>
                        <td style="text-align:center">
                            <button class="factura-pdf-btn" title="Descargar comprobante PDF"
                                    onclick="descargarFacturaPDF(${gxId}, '${comp}', this)">📄</button>
                        </td>
                    </tr>`;
            });
            html += '</tbody></table>';
        }
        todasCuentasBody.innerHTML = html;
    } catch (e) {
        todasCuentasBody.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar comprobantes.</p>';
    }
}

async function descargarFacturaPDF(gxId, comprobante, btn) {
    const original = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = '⏳'; }
    try {
        const url = `${BASE_URL}/api/factura-pdf?cliente=${gxId}&comprobante=${encodeURIComponent(comprobante)}`;
        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) { alert('No se pudo generar el PDF.'); return; }
        const blob = await res.blob();
        const objUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objUrl;
        a.download = `comprobante_${comprobante.replace(/[^A-Za-z0-9_-]+/g, '-')}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(objUrl), 1500);
    } catch (e) {
        alert('Error al descargar el PDF.');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
    }
}

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

// ── Préstamos ──────────────────────────────────────────────────────────────────

const prestamosBtn      = document.getElementById('prestamos-btn');
const prestamosModal    = document.getElementById('prestamos-modal');
const closePrestamosBtn = document.getElementById('close-prestamos');
const backFromPrestamos = document.getElementById('back-from-prestamos');
const prestamosBody     = document.getElementById('prestamos-body');
const toggleSolicitudBtn = document.getElementById('toggle-solicitud-btn');
const solicitudForm     = document.getElementById('solicitud-form');
const pEmpleadoSel      = document.getElementById('p-empleado-sel');
const pMontoInput       = document.getElementById('p-monto-input');
const pCuotasInput      = document.getElementById('p-cuotas-input');
const pCuotaInput       = document.getElementById('p-cuota-input');
const pMotivoInput      = document.getElementById('p-motivo-input');
const pSolicitarBtn     = document.getElementById('p-solicitar-btn');
const pSolicitarMsg     = document.getElementById('p-solicitar-msg');
const aprobarModal      = document.getElementById('aprobar-modal');
const closeAprobarBtn   = document.getElementById('close-aprobar');
const aprobarNombre     = document.getElementById('aprobar-empleado-nombre');
const apMontoInput      = document.getElementById('ap-monto-input');
const apCuotasInput     = document.getElementById('ap-cuotas-input');
const apCuotaInput      = document.getElementById('ap-cuota-input');
const apNotaInput       = document.getElementById('ap-nota-input');
const apSubmitBtn       = document.getElementById('ap-submit-btn');
const apMsg             = document.getElementById('ap-msg');
const pagoModal         = document.getElementById('pago-modal');
const closePagoBtn      = document.getElementById('close-pago');
const pagoSaldoInfo     = document.getElementById('pago-saldo-info');
const pagoMontoInput    = document.getElementById('pago-monto-input');
const pagoNotaInput     = document.getElementById('pago-nota-input');
const pagoSubmitBtn     = document.getElementById('pago-submit-btn');
const pagoMsg           = document.getElementById('pago-msg');

let currentPrestamoId = null;
let pagoDirecto       = false;   // true cuando jefe registra pago confirmado directo
const prestamosCountBadge = document.getElementById('prestamos-count');

async function actualizarBadgePrestamos() {
    try {
        const res  = await fetch(`${BASE_URL}/api/prestamos/pendientes-count`, { credentials: 'include' });
        const data = await res.json();
        const n    = data.count || 0;
        if (n > 0) {
            prestamosCountBadge.textContent = n;
            prestamosCountBadge.classList.remove('hidden');
        } else {
            prestamosCountBadge.classList.add('hidden');
        }
    } catch (e) {
        prestamosCountBadge.classList.add('hidden');
    }
}

async function cargarEmpleadosPrestamos() {
    try {
        const res  = await fetch(`${BASE_URL}/api/docs/empleados-lista`, { credentials: 'include' });
        const list = await res.json();
        pEmpleadoSel.innerHTML = '<option value="">Seleccioná un empleado...</option>';
        list.forEach(emp => {
            const opt = document.createElement('option');
            opt.value       = emp.id;
            opt.textContent = emp.nombre;
            pEmpleadoSel.appendChild(opt);
        });
    } catch (e) {
        pEmpleadoSel.innerHTML = '<option value="">Error al cargar empleados</option>';
    }
}

prestamosBtn.addEventListener('click', openPrestamosModal);
closePrestamosBtn.addEventListener('click', () => { prestamosModal.classList.add('hidden'); actualizarBadgePrestamos(); });
backFromPrestamos.addEventListener('click',  () => { prestamosModal.classList.add('hidden'); actualizarBadgePrestamos(); });

toggleSolicitudBtn.addEventListener('click', () => {
    const abierto = !solicitudForm.classList.contains('hidden');
    solicitudForm.classList.toggle('hidden', abierto);
    toggleSolicitudBtn.textContent = abierto ? '+ Nuevo Préstamo' : '— Cancelar';
});

async function openPrestamosModal() {
    prestamosModal.classList.remove('hidden');
    solicitudForm.classList.add('hidden');
    pSolicitarMsg.classList.add('hidden');

    const esGest = currentUser?.tipo_precio === 'jefe' || currentUser?.tipo_precio === 'admin';
    if (esGest) {
        toggleSolicitudBtn.classList.remove('hidden');
        toggleSolicitudBtn.textContent = '+ Nuevo Préstamo';
        await cargarEmpleadosPrestamos();
    } else {
        toggleSolicitudBtn.classList.add('hidden');
    }

    await loadPrestamos();
}

async function loadPrestamos() {
    prestamosBody.innerHTML = '<p style="text-align:center;padding:20px;color:var(--text-muted);">Cargando...</p>';
    try {
        const res  = await fetch(`${BASE_URL}/api/prestamos`, { credentials: 'include' });
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
            prestamosBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Sin préstamos registrados.</p>';
            return;
        }

        // Cargar pagos para cada préstamo activo/saldado
        const pagosMap = {};
        await Promise.all(
            data
              .filter(p => p.estado === 'aprobado' || p.estado === 'saldado')
              .map(async p => {
                  const r = await fetch(`${BASE_URL}/api/prestamos/${p.id}/pagos`, { credentials: 'include' });
                  pagosMap[p.id] = await r.json();
              })
        );

        prestamosBody.innerHTML = data.map(p => renderPrestamoCarta(p, pagosMap[p.id] || [])).join('');
        lucide.createIcons();
    } catch (e) {
        prestamosBody.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar préstamos.</p>';
    }
}

function renderPrestamoCarta(p, pagos) {
    const tipo   = currentUser?.tipo_precio;
    const esGest = tipo === 'jefe' || tipo === 'admin';
    const nombre = p.clientes?.nombre || '';

    const estadoBadge = {
        pendiente: '<span class="prestamo-badge badge-pendiente">⏳ Pendiente</span>',
        aprobado:  '<span class="prestamo-badge badge-aprobado">✅ Activo</span>',
        rechazado: '<span class="prestamo-badge badge-rechazado">❌ Rechazado</span>',
        saldado:   '<span class="prestamo-badge badge-saldado">🏁 Saldado</span>',
        cancelado: '<span class="prestamo-badge badge-rechazado">🚫 Cancelado</span>',
    }[p.estado] || p.estado;

    const fecha = p.created_at?.substring(0, 10);
    const monto = n => `$${parseFloat(n || 0).toLocaleString('es-AR', {minimumFractionDigits:0})}`;

    let cuerpo = '';

    if (p.estado === 'pendiente') {
        cuerpo = `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Solicitado</span>
                <span class="prestamo-monto-valor">${monto(p.monto_solicitado)}</span>
            </div>
            ${p.motivo ? `<p class="prestamo-motivo">"${p.motivo}"</p>` : ''}
            ${esGest ? `
            <div class="prestamo-acciones">
                <button class="doc-btn doc-btn--firmar" onclick="abrirAprobarModal('${p.id}','${nombre.replace(/'/g,"\\'")}',${p.monto_solicitado})">
                    ✅ Aprobar
                </button>
                <button class="doc-btn prestamo-btn-rechazar" onclick="rechazarPrestamo('${p.id}')">
                    ❌ Rechazar
                </button>
            </div>` : '<p class="prestamo-motivo" style="color:var(--text-muted)">Aguardando revisión del jefe.</p>'}
        `;
    } else if (p.estado === 'aprobado' || p.estado === 'saldado') {
        const saldo     = parseFloat(p.saldo_pendiente || 0);
        const aprobado  = parseFloat(p.monto_aprobado || 0);
        const pagado    = aprobado - saldo;
        const pct       = aprobado > 0 ? Math.round((pagado / aprobado) * 100) : 0;
        const cuotas    = p.cuotas_total || 1;
        const mCuota    = p.monto_cuota  || 0;

        cuerpo = `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Aprobado</span>
                <span class="prestamo-monto-valor">${monto(p.monto_aprobado)}</span>
            </div>
            ${saldo > 0 ? `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Saldo pendiente</span>
                <span class="prestamo-monto-valor" style="color:#dc2626">${monto(saldo)}</span>
            </div>` : ''}
            ${mCuota > 0 ? `<p class="prestamo-motivo">${cuotas} cuota${cuotas>1?'s':''} de ${monto(mCuota)}</p>` : ''}
            ${p.condiciones_nota ? `<p class="prestamo-motivo">${p.condiciones_nota}</p>` : ''}
            <div class="prestamo-barra-wrap">
                <div class="prestamo-barra" style="width:${pct}%"></div>
            </div>
            <p class="prestamo-motivo" style="text-align:right">${monto(pagado)} pagado de ${monto(aprobado)}</p>
            ${renderPagos(pagos, esGest, p.estado === 'aprobado' && saldo > 0)}
        `;
    } else if (p.estado === 'rechazado') {
        cuerpo = `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Solicitado</span>
                <span class="prestamo-monto-valor">${monto(p.monto_solicitado)}</span>
            </div>
            ${p.nota_rechazo ? `<p class="prestamo-motivo">Motivo: "${p.nota_rechazo}"</p>` : ''}
        `;
    }

    return `
        <div class="prestamo-card">
            <div class="prestamo-card-header">
                ${esGest && nombre ? `<span class="prestamo-empleado">${nombre}</span>` : ''}
                ${estadoBadge}
                <span class="prestamo-fecha">${fecha}</span>
            </div>
            ${cuerpo}
        </div>`;
}

function renderPagos(pagos, esGest, puedeInformar) {
    if (!pagos || pagos.length === 0) {
        if (!puedeInformar || !esGest) return '';
        return '';   // prestamoId no disponible en este punto, se maneja desde renderPrestamoCarta
    }

    const monto = n => `$${parseFloat(n || 0).toLocaleString('es-AR', {minimumFractionDigits:0})}`;
    let html = '<div class="prestamo-pagos-lista">';
    let prestamoId = '';

    pagos.forEach(pago => {
        prestamoId = pago.prestamo_id;
        const fecha = pago.fecha_informado?.substring(0, 10);
        if (pago.estado === 'informado') {
            html += `
                <div class="pago-item pago-informado">
                    <div>
                        <span class="pago-icono">⏳</span>
                        <strong>${monto(pago.monto)}</strong>
                        <span class="pago-fecha">${fecha} · informado</span>
                        ${pago.nota_empleado ? `<span class="pago-nota">"${pago.nota_empleado}"</span>` : ''}
                    </div>
                    ${esGest ? `
                    <div class="pago-acciones">
                        <button class="pago-btn pago-btn-ok" onclick="confirmarPago('${pago.id}')">✅</button>
                        <button class="pago-btn pago-btn-no" onclick="rechazarPago('${pago.id}')">❌</button>
                    </div>` : ''}
                </div>`;
        } else if (pago.estado === 'confirmado') {
            const fConf = pago.fecha_confirmado?.substring(0, 10);
            html += `
                <div class="pago-item pago-confirmado">
                    <span class="pago-icono">✅</span>
                    <strong>${monto(pago.monto)}</strong>
                    <span class="pago-fecha">${fecha} · confirmado ${fConf}</span>
                </div>`;
        } else if (pago.estado === 'rechazado') {
            html += `
                <div class="pago-item pago-rechazado">
                    <span class="pago-icono">❌</span>
                    <strong>${monto(pago.monto)}</strong>
                    <span class="pago-fecha">${fecha} · rechazado</span>
                    ${pago.nota_jefe ? `<span class="pago-nota">"${pago.nota_jefe}"</span>` : ''}
                </div>`;
        }
    });
    html += '</div>';

    // Botón de pago — solo jefe/admin pueden registrar pagos directos
    const hayInformado = pagos.some(p => p.estado === 'informado');
    if (puedeInformar && !hayInformado && esGest) {
        html += `
            <div class="prestamo-acciones">
                <button class="doc-btn doc-btn--firmar" onclick="abrirPagoDirectoModal('${prestamoId}')">
                    💰 Registrar Pago
                </button>
            </div>`;
    }
    return html;
}

// Redefinir para pasar el prestamoId correctamente
function renderPrestamoCarta(p, pagos) {
    const tipo   = currentUser?.tipo_precio;
    const esGest = tipo === 'jefe' || tipo === 'admin';
    const nombre = p.clientes?.nombre || '';
    const estadoBadge = {
        pendiente: '<span class="prestamo-badge badge-pendiente">⏳ Pendiente</span>',
        aprobado:  '<span class="prestamo-badge badge-aprobado">✅ Activo</span>',
        rechazado: '<span class="prestamo-badge badge-rechazado">❌ Rechazado</span>',
        saldado:   '<span class="prestamo-badge badge-saldado">🏁 Saldado</span>',
        cancelado: '<span class="prestamo-badge badge-rechazado">🚫 Cancelado</span>',
    }[p.estado] || p.estado;
    const fecha = p.created_at?.substring(0, 10);
    const monto = n => `$${parseFloat(n || 0).toLocaleString('es-AR', {minimumFractionDigits:0})}`;

    let cuerpo = '';
    if (p.estado === 'pendiente') {
        cuerpo = `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Solicitado</span>
                <span class="prestamo-monto-valor">${monto(p.monto_solicitado)}</span>
            </div>
            ${p.motivo ? `<p class="prestamo-motivo">"${p.motivo}"</p>` : ''}
            ${esGest ? `
            <div class="prestamo-acciones">
                <button class="doc-btn doc-btn--firmar" onclick="abrirAprobarModal('${p.id}','${nombre.replace(/'/g,"\\'")}',${p.monto_solicitado})">✅ Aprobar</button>
                <button class="doc-btn prestamo-btn-rechazar" onclick="rechazarPrestamo('${p.id}')">❌ Rechazar</button>
            </div>` : '<p class="prestamo-motivo" style="color:var(--text-muted);">Aguardando revisión.</p>'}`;

    } else if (p.estado === 'aprobado' || p.estado === 'saldado') {
        const saldo    = parseFloat(p.saldo_pendiente || 0);
        const aprobado = parseFloat(p.monto_aprobado || 0);
        const pagado   = aprobado - saldo;
        const pct      = aprobado > 0 ? Math.round((pagado / aprobado) * 100) : 0;
        const cuotas   = p.cuotas_total || 1;
        const mCuota   = p.monto_cuota  || 0;
        const hayInformado = pagos.some(pg => pg.estado === 'informado');
        const puedeInformar = p.estado === 'aprobado' && saldo > 0 && !hayInformado;

        cuerpo = `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Aprobado</span>
                <span class="prestamo-monto-valor">${monto(aprobado)}</span>
            </div>
            ${saldo > 0 ? `<div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Saldo pendiente</span>
                <span class="prestamo-monto-valor" style="color:#dc2626">${monto(saldo)}</span>
            </div>` : ''}
            ${mCuota > 0 ? `<p class="prestamo-motivo">${cuotas} cuota${cuotas>1?'s':''} de ${monto(mCuota)}</p>` : ''}
            ${p.condiciones_nota ? `<p class="prestamo-motivo">${p.condiciones_nota}</p>` : ''}
            <div class="prestamo-barra-wrap">
                <div class="prestamo-barra" style="width:${pct}%"></div>
            </div>
            <p class="prestamo-motivo" style="text-align:right;margin-top:2px;">${monto(pagado)} pagado de ${monto(aprobado)}</p>
            ${renderPagosDe(p.id, pagos, esGest, puedeInformar)}
        `;
    } else if (p.estado === 'rechazado') {
        cuerpo = `
            <div class="prestamo-monto-row">
                <span class="prestamo-monto-label">Solicitado</span>
                <span class="prestamo-monto-valor">${monto(p.monto_solicitado)}</span>
            </div>
            ${p.nota_rechazo ? `<p class="prestamo-motivo">Motivo: "${p.nota_rechazo}"</p>` : ''}`;
    }

    return `
        <div class="prestamo-card">
            <div class="prestamo-card-header">
                ${esGest && nombre ? `<span class="prestamo-empleado">${nombre}</span>` : ''}
                ${estadoBadge}
                <span class="prestamo-fecha">${fecha}</span>
            </div>
            ${cuerpo}
        </div>`;
}

function renderPagosDe(prestamoId, pagos, esGest, puedeInformar) {
    const monto = n => `$${parseFloat(n || 0).toLocaleString('es-AR', {minimumFractionDigits:0})}`;
    let html = '';
    if (pagos && pagos.length > 0) {
        html += '<div class="prestamo-pagos-lista">';
        pagos.forEach(pago => {
            const fecha = pago.fecha_informado?.substring(0, 10);
            if (pago.estado === 'informado') {
                html += `
                    <div class="pago-item pago-informado">
                        <div class="pago-info">
                            <span>⏳ <strong>${monto(pago.monto)}</strong> · ${fecha}</span>
                            ${pago.nota_empleado ? `<span class="pago-nota">"${pago.nota_empleado}"</span>` : ''}
                        </div>
                        ${esGest ? `
                        <div class="pago-acciones">
                            <button class="pago-btn pago-btn-ok" onclick="confirmarPago('${pago.id}')">✅</button>
                            <button class="pago-btn pago-btn-no" onclick="rechazarPago('${pago.id}')">❌</button>
                        </div>` : ''}
                    </div>`;
            } else if (pago.estado === 'confirmado') {
                html += `
                    <div class="pago-item pago-confirmado">
                        ✅ <strong>${monto(pago.monto)}</strong>
                        <span class="pago-fecha"> · ${fecha}</span>
                    </div>`;
            } else {
                html += `
                    <div class="pago-item pago-rechazado">
                        ❌ <strong>${monto(pago.monto)}</strong> · rechazado
                        ${pago.nota_jefe ? `<span class="pago-nota"> "${pago.nota_jefe}"</span>` : ''}
                    </div>`;
            }
        });
        html += '</div>';
    }
    if (puedeInformar) {
        html += `<div class="prestamo-acciones">
            <button class="doc-btn doc-btn--firmar" onclick="abrirPagoModal('${prestamoId}')">
                💸 Informar Pago
            </button>
        </div>`;
    }
    return html;
}

// Crear préstamo (solo jefe/admin)
pSolicitarBtn.addEventListener('click', async () => {
    const empleadoId = pEmpleadoSel.value;
    const monto      = parseFloat(pMontoInput.value);
    const cuotas     = parseInt(pCuotasInput.value) || 1;
    const montoCuota = parseFloat(pCuotaInput.value) || 0;
    const nota       = pMotivoInput.value.trim();
    pSolicitarMsg.classList.add('hidden');

    if (!empleadoId)             { mostrarDocMsg(pSolicitarMsg, 'Seleccioná un empleado', 'error'); return; }
    if (!monto || monto <= 0)    { mostrarDocMsg(pSolicitarMsg, 'Ingresá un monto válido', 'error'); return; }
    if (cuotas < 1)              { mostrarDocMsg(pSolicitarMsg, 'Las cuotas deben ser al menos 1', 'error'); return; }

    pSolicitarBtn.disabled    = true;
    pSolicitarBtn.textContent = 'Guardando...';
    try {
        const res  = await fetch(`${BASE_URL}/api/prestamos`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                empleado_id:      empleadoId,
                monto,
                cuotas,
                monto_cuota:      montoCuota || null,
                condiciones_nota: nota || null,
            }),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            mostrarDocMsg(pSolicitarMsg, '✅ Préstamo creado exitosamente', 'ok');
            pEmpleadoSel.value = '';
            pMontoInput.value  = '';
            pCuotasInput.value = '1';
            pCuotaInput.value  = '';
            pMotivoInput.value = '';
            solicitudForm.classList.add('hidden');
            toggleSolicitudBtn.textContent = '+ Nuevo Préstamo';
            await loadPrestamos();
        } else {
            mostrarDocMsg(pSolicitarMsg, data.error || 'Error desconocido', 'error');
        }
    } catch (e) {
        mostrarDocMsg(pSolicitarMsg, 'Error al conectar', 'error');
    } finally {
        pSolicitarBtn.disabled    = false;
        pSolicitarBtn.textContent = 'Crear Préstamo';
    }
});

// Aprobar préstamo
closeAprobarBtn.addEventListener('click', () => aprobarModal.classList.add('hidden'));

function abrirAprobarModal(prestamoId, nombreEmp, montoSolicitado) {
    currentPrestamoId = prestamoId;
    aprobarNombre.textContent = `${nombreEmp} · solicitó $${parseFloat(montoSolicitado).toLocaleString('es-AR')}`;
    apMontoInput.value  = montoSolicitado;
    apCuotasInput.value = 1;
    apCuotaInput.value  = '';
    apNotaInput.value   = '';
    apMsg.classList.add('hidden');
    aprobarModal.classList.remove('hidden');
}

apSubmitBtn.addEventListener('click', async () => {
    const montoAp = parseFloat(apMontoInput.value);
    const cuotas  = parseInt(apCuotasInput.value) || 1;
    const mCuota  = parseFloat(apCuotaInput.value) || 0;
    const nota    = apNotaInput.value.trim();
    apMsg.classList.add('hidden');

    if (!montoAp || montoAp <= 0) { mostrarDocMsg(apMsg, 'Ingresá un monto válido', 'error'); return; }

    apSubmitBtn.disabled    = true;
    apSubmitBtn.textContent = 'Aprobando...';
    try {
        const res  = await fetch(`${BASE_URL}/api/prestamos/${currentPrestamoId}/aprobar`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monto_aprobado: montoAp, cuotas, monto_cuota: mCuota, condiciones_nota: nota }),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            aprobarModal.classList.add('hidden');
            await loadPrestamos();
        } else {
            mostrarDocMsg(apMsg, data.error || 'Error', 'error');
        }
    } catch (e) {
        mostrarDocMsg(apMsg, 'Error al conectar', 'error');
    } finally {
        apSubmitBtn.disabled    = false;
        apSubmitBtn.textContent = 'Confirmar Aprobación';
    }
});

async function rechazarPrestamo(prestamoId) {
    const nota = prompt('Motivo del rechazo (opcional):') ?? null;
    if (nota === null) return; // canceló
    try {
        await fetch(`${BASE_URL}/api/prestamos/${prestamoId}/rechazar`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nota }),
        });
        await loadPrestamos();
    } catch (e) { alert('Error al rechazar'); }
}

// Registrar / Informar pago
closePagoBtn.addEventListener('click', () => { pagoModal.classList.add('hidden'); pagoDirecto = false; });

function abrirPagoDirectoModal(prestamoId) {
    pagoDirecto         = true;
    currentPrestamoId   = prestamoId;
    pagoSaldoInfo.textContent = 'Registrar pago — se confirma directamente';
    pagoMontoInput.value = '';
    pagoNotaInput.value  = '';
    pagoMsg.classList.add('hidden');
    pagoModal.classList.remove('hidden');
}

function abrirPagoModal(prestamoId) {
    pagoDirecto         = false;
    currentPrestamoId   = prestamoId;
    pagoSaldoInfo.textContent = '';
    pagoMontoInput.value = '';
    pagoNotaInput.value  = '';
    pagoMsg.classList.add('hidden');
    pagoModal.classList.remove('hidden');
}

pagoSubmitBtn.addEventListener('click', async () => {
    const monto = parseFloat(pagoMontoInput.value);
    const nota  = pagoNotaInput.value.trim();
    pagoMsg.classList.add('hidden');

    if (!monto || monto <= 0) { mostrarDocMsg(pagoMsg, 'Ingresá un monto válido', 'error'); return; }

    pagoSubmitBtn.disabled    = true;
    pagoSubmitBtn.textContent = 'Guardando...';

    const endpoint = pagoDirecto
        ? `${BASE_URL}/api/prestamos/${currentPrestamoId}/pago-directo`
        : `${BASE_URL}/api/prestamos/${currentPrestamoId}/pagos`;

    try {
        const res  = await fetch(endpoint, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monto, nota }),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            const msg = pagoDirecto ? '✅ Pago registrado y confirmado.' : '✅ Pago informado. El jefe lo confirmará pronto.';
            mostrarDocMsg(pagoMsg, msg, 'ok');
            setTimeout(async () => {
                pagoModal.classList.add('hidden');
                pagoDirecto = false;
                await loadPrestamos();
                actualizarBadgePrestamos();
            }, 1500);
        } else {
            mostrarDocMsg(pagoMsg, data.error || 'Error', 'error');
        }
    } catch (e) {
        mostrarDocMsg(pagoMsg, 'Error al conectar', 'error');
    } finally {
        pagoSubmitBtn.disabled    = false;
        pagoSubmitBtn.textContent = 'Confirmar Pago';
    }
});

async function confirmarPago(pagoId) {
    try {
        const res  = await fetch(`${BASE_URL}/api/prestamos/pagos/${pagoId}/confirmar`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nota: '' }),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            await loadPrestamos();
            actualizarBadgePrestamos();
        } else {
            alert('Error: ' + (data.error || 'desconocido'));
        }
    } catch (e) { alert('Error al confirmar pago'); }
}

async function rechazarPago(pagoId) {
    const nota = prompt('Motivo del rechazo (opcional):') ?? null;
    if (nota === null) return;
    try {
        await fetch(`${BASE_URL}/api/prestamos/pagos/${pagoId}/rechazar`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nota }),
        });
        await loadPrestamos();
        actualizarBadgePrestamos();
    } catch (e) { alert('Error'); }
}

// ── Documentos de empleados ────────────────────────────────────────────────────

const TIPO_LABEL = {
    recibo_sueldo:   'Recibo de Sueldo',
    credencial_art:  'Credencial ART',
    seguro_vehiculo: 'Seguro Vehículo',
    carnet_conducir: 'Carnet de Conducir',
};

let activeDocsTab = 'recibos';

// Panel DOM refs (por tab)
const panelRecibos      = document.getElementById('docs-panel-recibos');
const panelDocumentacion = document.getElementById('docs-panel-documentacion');
const panelSubir        = document.getElementById('docs-panel-subir');
const tabSubirBtn       = document.getElementById('docs-tab-subir');

docsBtn.addEventListener('click', () => openDocsModal());
closeDocsBtn.addEventListener('click', () => docsModal.classList.add('hidden'));
backFromDocs.addEventListener('click',  () => docsModal.classList.add('hidden'));

// Cambio de pestaña
document.querySelectorAll('.docs-tab').forEach(tab => {
    tab.addEventListener('click', () => {
        activeDocsTab = tab.dataset.tab;
        document.querySelectorAll('.docs-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        panelRecibos.classList.add('hidden');
        panelDocumentacion.classList.add('hidden');
        panelSubir.classList.add('hidden');

        if (activeDocsTab === 'recibos') {
            panelRecibos.classList.remove('hidden');
            loadDocs('recibos');
        } else if (activeDocsTab === 'documentacion') {
            panelDocumentacion.classList.remove('hidden');
            loadDocs('documentacion');
        } else if (activeDocsTab === 'subir') {
            panelSubir.classList.remove('hidden');
        }
    });
});

async function openDocsModal() {
    docsModal.classList.remove('hidden');
    const tipo     = currentUser?.tipo_precio;
    const esGestor = tipo === 'jefe' || tipo === 'admin';

    // Mostrar pestaña "Subir" solo para gestores
    tabSubirBtn.classList.toggle('hidden', !esGestor);
    if (esGestor) await cargarEmpleadosSelector();

    // Arrancar siempre en la pestaña Recibos
    activeDocsTab = 'recibos';
    document.querySelectorAll('.docs-tab').forEach(t => t.classList.remove('active'));
    document.querySelector('.docs-tab[data-tab="recibos"]').classList.add('active');
    panelRecibos.classList.remove('hidden');
    panelDocumentacion.classList.add('hidden');
    panelSubir.classList.add('hidden');

    await loadDocs('recibos');
}

async function cargarEmpleadosSelector() {
    try {
        const res  = await fetch(`${BASE_URL}/api/docs/empleados-lista`, { credentials: 'include' });
        const list = await res.json();
        docsEmpleadoSel.innerHTML = '<option value="">Seleccioná un empleado...</option>';
        list.forEach(emp => {
            const opt = document.createElement('option');
            opt.value       = emp.id;
            opt.textContent = `${emp.nombre} (${emp.tipo_precio})`;
            docsEmpleadoSel.appendChild(opt);
        });
    } catch (e) {
        docsEmpleadoSel.innerHTML = '<option value="">Error al cargar empleados</option>';
    }
}

async function loadDocs(categoria) {
    const panel = categoria === 'recibos' ? panelRecibos : panelDocumentacion;
    panel.innerHTML = '<p style="text-align:center;padding:20px;color:var(--text-muted);">Cargando...</p>';

    try {
        const res  = await fetch(`${BASE_URL}/api/docs?categoria=${categoria}`, { credentials: 'include' });
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
            const msg = categoria === 'recibos'
                ? 'Sin recibos de sueldo aún.'
                : 'Sin documentación cargada aún.';
            panel.innerHTML = `<p style="text-align:center;padding:30px;color:var(--text-muted);">${msg}</p>`;
            return;
        }

        panel.innerHTML = categoria === 'recibos'
            ? renderRecibos(data)
            : renderDocumentacion(data);
        lucide.createIcons();
    } catch (e) {
        panel.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar.</p>';
    }
}

function renderRecibos(docs) {
    const miId = currentUser?.id;
    // Agrupar por período
    const grupos = {};
    docs.forEach(doc => {
        const key = doc.periodo || 'Sin período';
        if (!grupos[key]) grupos[key] = [];
        grupos[key].push(doc);
    });

    let html = '';
    Object.entries(grupos).forEach(([periodo, lista]) => {
        html += `<div class="doc-grupo-titulo">${periodo}</div>`;
        lista.forEach(doc => {
            const esFirmado = doc.estado === 'firmado';
            const esMio     = String(doc.empleado_id) === String(miId);
            html += `
                <div class="doc-card">
                    <div class="doc-info">
                        <strong class="doc-nombre">${doc.nombre_archivo}</strong>
                        ${esFirmado
                            ? `<span class="doc-estado estado-firmado">✅ Firmado el ${doc.firma_timestamp?.substring(0,10)} — ${doc.firma_nombre}</span>`
                            : `<span class="doc-estado estado-pendiente">⏳ Pendiente de firma</span>`}
                    </div>
                    <div class="doc-acciones">
                        <button class="doc-btn" onclick="descargarDoc('${doc.id}','${doc.nombre_archivo}')" title="Descargar">
                            <i data-lucide="download"></i>
                        </button>
                        ${!esFirmado && esMio ? `
                        <button class="doc-btn doc-btn--firmar" onclick="openSignPad('${doc.id}','${doc.nombre_archivo.replace(/'/g,"\\'")}')">
                            ✍️ Firmar
                        </button>` : ''}
                    </div>
                </div>`;
        });
    });
    return html;
}

function renderDocumentacion(docs) {
    const miId = currentUser?.id;
    // Agrupar por tipo de documento
    const grupos = {};
    docs.forEach(doc => {
        const key = TIPO_LABEL[doc.tipo] || doc.tipo;
        if (!grupos[key]) grupos[key] = [];
        grupos[key].push(doc);
    });

    let html = '';
    Object.entries(grupos).forEach(([tipoLabel, lista]) => {
        html += `<div class="doc-grupo-titulo">${tipoLabel}</div>`;
        lista.forEach(doc => {
            const fecha = doc.created_at ? doc.created_at.substring(0, 10) : '';
            html += `
                <div class="doc-card">
                    <div class="doc-info">
                        <strong class="doc-nombre">${doc.nombre_archivo}</strong>
                        <span class="doc-estado" style="color:var(--text-muted);">Subido el ${fecha}</span>
                    </div>
                    <div class="doc-acciones">
                        <button class="doc-btn" onclick="descargarDoc('${doc.id}','${doc.nombre_archivo}')" title="Descargar">
                            <i data-lucide="download"></i>
                        </button>
                    </div>
                </div>`;
        });
    });
    return html;
}

async function descargarDoc(docId, nombre) {
    try {
        const res  = await fetch(`${BASE_URL}/api/docs/descargar/${docId}`, { credentials: 'include' });
        const data = await res.json();
        if (data.url) {
            const a = document.createElement('a');
            a.href   = data.url;
            a.target = '_blank';
            a.rel    = 'noopener';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } else {
            alert('Error: ' + (data.error || 'No se pudo descargar'));
        }
    } catch (e) {
        alert('Error al descargar el documento');
    }
}

// Subida (admin / jefe)
docsFileInput.addEventListener('change', () => {
    docsFileName.textContent = docsFileInput.files[0]?.name || 'Ningún archivo seleccionado';
});

docsUploadBtn.addEventListener('click', async () => {
    const empleadoId = docsEmpleadoSel.value;
    const tipo       = docsTipoSel.value;
    const periodo    = docsPeriodoInput.value.trim();
    const file       = docsFileInput.files[0];

    docsUploadMsg.classList.add('hidden');
    if (!empleadoId) { mostrarDocMsg(docsUploadMsg, 'Seleccioná un empleado', 'error'); return; }
    if (!file)       { mostrarDocMsg(docsUploadMsg, 'Seleccioná un archivo PDF', 'error'); return; }

    docsUploadBtn.disabled    = true;
    docsUploadBtn.textContent = 'Subiendo...';

    const fd = new FormData();
    fd.append('empleado_id', empleadoId);
    fd.append('tipo',        tipo);
    fd.append('periodo',     periodo);
    fd.append('archivo',     file);

    try {
        const res  = await fetch(`${BASE_URL}/api/docs/subir`, { method: 'POST', credentials: 'include', body: fd });
        const data = await res.json();
        if (res.ok && data.ok) {
            mostrarDocMsg(docsUploadMsg, '✅ Documento subido exitosamente', 'ok');
            docsFileInput.value      = '';
            docsFileName.textContent = 'Ningún archivo seleccionado';
            docsPeriodoInput.value   = '';
        } else {
            mostrarDocMsg(docsUploadMsg, 'Error: ' + (data.error || 'desconocido'), 'error');
        }
    } catch (e) {
        mostrarDocMsg(docsUploadMsg, 'Error al conectar con el servidor', 'error');
    } finally {
        docsUploadBtn.disabled    = false;
        docsUploadBtn.textContent = 'Subir Documento';
    }
});

function mostrarDocMsg(el, texto, tipo) {
    el.textContent = texto;
    el.style.color = tipo === 'ok' ? '#28a745' : '#dc2626';
    el.classList.remove('hidden');
}

// ── Firma Digital ──────────────────────────────────────────────────────────────

let signaturePad  = null;
let currentDocId  = null;

closeFirmaBtn.addEventListener('click', () => firmaModal.classList.add('hidden'));

firmaLimpiarBtn.addEventListener('click', () => {
    if (signaturePad) signaturePad.clear();
    firmaMsgEl.classList.add('hidden');
});

firmaConfirmarBtn.addEventListener('click', submitFirma);

function openSignPad(docId, docNombre) {
    currentDocId = docId;
    firmaDocNombre.textContent = docNombre;
    firmaMsgEl.classList.add('hidden');
    firmaModal.classList.remove('hidden');

    // Inicializar o limpiar el canvas
    const canvas = document.getElementById('firma-canvas');
    // Ajustar tamaño real del canvas al display
    const rect   = canvas.getBoundingClientRect();
    canvas.width  = rect.width  || 320;
    canvas.height = rect.height || 200;

    if (signaturePad) {
        signaturePad.clear();
    } else {
        signaturePad = new SignaturePad(canvas, {
            backgroundColor: 'rgb(255,255,255)',
            penColor:        'rgb(10,10,40)',
            minWidth: 1.5,
            maxWidth: 3,
        });
    }
}

async function submitFirma() {
    if (!signaturePad || signaturePad.isEmpty()) {
        mostrarDocMsg(firmaMsgEl, 'Por favor dibujá tu firma primero', 'error');
        return;
    }

    const firmaData = signaturePad.toDataURL('image/png');

    firmaConfirmarBtn.disabled   = true;
    firmaConfirmarBtn.textContent = 'Firmando...';
    firmaMsgEl.classList.add('hidden');

    try {
        const res  = await fetch(`${BASE_URL}/api/docs/firmar/${currentDocId}`, {
            method:      'POST',
            credentials: 'include',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify({ firma_data: firmaData }),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            mostrarDocMsg(firmaMsgEl, '✅ ¡Documento firmado exitosamente!', 'ok');
            setTimeout(async () => {
                firmaModal.classList.add('hidden');
                await loadDocs();
            }, 2000);
        } else {
            mostrarDocMsg(firmaMsgEl, 'Error: ' + (data.error || 'desconocido'), 'error');
        }
    } catch (e) {
        mostrarDocMsg(firmaMsgEl, 'Error al conectar con el servidor', 'error');
    } finally {
        firmaConfirmarBtn.disabled   = false;
        firmaConfirmarBtn.textContent = 'Confirmar Firma';
    }
}

// ── Faltantes ──────────────────────────────────────────────────────────────────

const ESTADO_LABEL = {
    faltante:   '🔴 Faltante',
    en_gestion: '🟡 En gestión',
    resuelto:   '🟢 Resuelto',
};
const ESTADO_CLASS = {
    faltante:   'faltante-estado--faltante',
    en_gestion: 'faltante-estado--gestion',
    resuelto:   'faltante-estado--resuelto',
};

// Días de tolerancia antes de mostrar alerta
const ALERTA_DIAS_FALTANTE  = 2;
const ALERTA_DIAS_GESTION   = 5;

function diasDesde(isoStr) {
    if (!isoStr) return null;
    const diff = Date.now() - new Date(isoStr).getTime();
    return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function alertaFaltante(f) {
    if (f.estado === 'resuelto') return null;
    if (f.estado === 'faltante') {
        const d = diasDesde(f.creado_en);
        return d >= ALERTA_DIAS_FALTANTE ? `⚠️ Sin gestión hace ${d} día${d !== 1 ? 's' : ''}` : null;
    }
    if (f.estado === 'en_gestion') {
        const d = diasDesde(f.gestion_en || f.actualizado_en || f.creado_en);
        return d >= ALERTA_DIAS_GESTION ? `🚨 En gestión hace ${d} día${d !== 1 ? 's' : ''}` : null;
    }
    return null;
}

faltantesBtn.addEventListener('click', () => {
    faltantesModal.classList.remove('hidden');
    loadFaltantes();
});
closeFaltantesBtn.addEventListener('click',    () => faltantesModal.classList.add('hidden'));
backFromFaltantesBtn.addEventListener('click', () => faltantesModal.classList.add('hidden'));

async function actualizarBadgeFaltantes() {
    try {
        const res  = await fetch(`${BASE_URL}/api/faltantes`, { credentials: 'include' });
        if (!res.ok) return;
        const data = await res.json();
        // Badge muestra pendientes + alertas
        const conAlerta  = data.filter(f => alertaFaltante(f)).length;
        const pendientes = data.filter(f => f.estado !== 'resuelto').length;
        const num = conAlerta > 0 ? conAlerta : pendientes;
        if (num > 0) {
            faltantesCount.textContent = num;
            faltantesCount.classList.remove('hidden');
            faltantesCount.style.background = conAlerta > 0 ? '#dc2626' : '';
        } else {
            faltantesCount.classList.add('hidden');
        }
    } catch (e) {}
}

function buildFaltanteCard(f, tipo) {
    const esGestor       = tipo === 'farmaceutico' || tipo === 'jefe' || tipo === 'admin';
    const esJefeDeposito = tipo === 'jefe_deposito';
    const puedeEliminar  = esJefeDeposito || tipo === 'admin';
    const alerta         = alertaFaltante(f);

    const fecha     = f.creado_en     ? new Date(f.creado_en).toLocaleDateString('es-AR',     { day:'2-digit', month:'2-digit', year:'numeric' }) : '';
    const actFecha  = f.actualizado_en ? new Date(f.actualizado_en).toLocaleDateString('es-AR', { day:'2-digit', month:'2-digit', year:'numeric' }) : '';
    const gestFecha = f.gestion_en    ? new Date(f.gestion_en).toLocaleDateString('es-AR',    { day:'2-digit', month:'2-digit', year:'numeric' }) : '';

    let botones = '';
    if (esGestor) {
        if (f.estado === 'faltante') {
            botones += `<button class="faltante-btn-accion btn-gestion trigger-gestion" data-id="${f.id}">📋 En gestión</button>`;
        } else if (f.estado === 'en_gestion') {
            botones += `<button class="faltante-btn-accion btn-gestion" data-id="${f.id}" data-estado="faltante">↩ Reabrir</button>`;
            botones += `<button class="faltante-btn-accion btn-resuelto" data-id="${f.id}" data-estado="resuelto">✅ Resuelto</button>`;
        } else if (f.estado === 'resuelto') {
            botones += `<button class="faltante-btn-accion btn-gestion" data-id="${f.id}" data-estado="faltante">↩ Reabrir</button>`;
        }
    }
    if (esJefeDeposito && f.estado === 'resuelto') {
        botones += `<button class="faltante-btn-accion btn-confirmar" data-id="${f.id}">📦 Confirmar recepción</button>`;
    }
    if (puedeEliminar) {
        botones += `<button class="faltante-btn-accion btn-eliminar" data-id="${f.id}">🗑</button>`;
    }

    return `
    <div class="faltante-card${alerta ? ' faltante-card--alerta' : ''}" id="faltante-card-${f.id}">
        <div class="faltante-card-top">
            <span class="faltante-estado ${ESTADO_CLASS[f.estado] || ''}">${ESTADO_LABEL[f.estado] || f.estado}</span>
            <span class="faltante-meta">Por ${f.creado_por_nombre || '—'} · ${fecha}</span>
        </div>
        ${alerta ? `<div class="faltante-alerta">${alerta}</div>` : ''}
        <p class="faltante-producto">${f.producto}</p>
        ${f.nota ? `<p class="faltante-nota">"${f.nota}"</p>` : ''}
        ${f.gestion_por_nombre ? `<p class="faltante-act-info">📋 Gestión: ${f.gestion_por_nombre}${gestFecha ? ' · ' + gestFecha : ''}${f.nota_gestion ? ` — "${f.nota_gestion}"` : ''}</p>` : ''}
        ${f.estado === 'resuelto' && f.dias_entrega ? `<p class="faltante-act-info">🚚 Entrega estimada: ${f.dias_entrega} día${f.dias_entrega !== 1 ? 's' : ''}</p>` : ''}
        ${f.estado === 'resuelto' && f.actualizado_por_nombre ? `<p class="faltante-act-info">✅ Resuelto por ${f.actualizado_por_nombre}${actFecha ? ' · ' + actFecha : ''}</p>` : ''}
        ${botones ? `<div class="faltante-acciones" id="acciones-${f.id}">${botones}</div>` : ''}
        <div class="faltante-gestion-form hidden" id="gestion-form-${f.id}">
            <textarea placeholder="Nota sobre la gestión (opcional)" class="docs-input faltante-nota-gestion-input" rows="2" style="margin-top:6px;width:100%;resize:vertical;"></textarea>
            <div style="display:flex;gap:8px;margin-top:6px;">
                <button class="faltante-btn-accion btn-gestion confirm-gestion" data-id="${f.id}">Confirmar</button>
                <button class="faltante-btn-accion btn-gestion cancel-gestion" data-id="${f.id}">Cancelar</button>
            </div>
        </div>
        <div class="faltante-resolucion-form hidden" id="resolve-form-${f.id}">
            <input type="number" min="1" max="365" placeholder="Días estimados de entrega" class="docs-input faltante-dias-input" style="margin-top:6px;">
            <div style="display:flex;gap:8px;margin-top:6px;">
                <button class="faltante-btn-accion btn-resuelto confirm-resolve" data-id="${f.id}">Confirmar</button>
                <button class="faltante-btn-accion btn-gestion cancel-resolve" data-id="${f.id}">Cancelar</button>
            </div>
        </div>
    </div>`;
}

async function loadFaltantes() {
    const tipo = currentUser?.tipo_precio;
    faltantesBody.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:24px 0;">Cargando...</p>';

    if (tipo === 'jefe_deposito') {
        faltantesFormSection.classList.remove('hidden');
    } else {
        faltantesFormSection.classList.add('hidden');
    }

    try {
        const res  = await fetch(`${BASE_URL}/api/faltantes`, { credentials: 'include' });
        const data = await res.json();
        if (!res.ok) { faltantesBody.innerHTML = `<p class="docs-msg error-msg">${data.error}</p>`; return; }

        if (!data.length) {
            faltantesBody.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:24px 0;">No hay productos faltantes registrados.</p>';
            actualizarBadgeFaltantes();
            return;
        }

        // Resumen para admin/jefe
        const esAdmin = tipo === 'admin' || tipo === 'jefe';
        if (esAdmin) {
            const total      = data.length;
            const pendientes = data.filter(f => f.estado === 'faltante').length;
            const enGestion  = data.filter(f => f.estado === 'en_gestion').length;
            const resueltos  = data.filter(f => f.estado === 'resuelto').length;
            const conAlerta  = data.filter(f => alertaFaltante(f)).length;
            faltantesBody.innerHTML = `
            <div class="faltante-resumen">
                <div class="faltante-resumen-stat"><span class="faltante-resumen-num">${pendientes}</span><span>Pendientes</span></div>
                <div class="faltante-resumen-stat"><span class="faltante-resumen-num" style="color:#92400e">${enGestion}</span><span>En gestión</span></div>
                <div class="faltante-resumen-stat"><span class="faltante-resumen-num" style="color:#065f46">${resueltos}</span><span>Resueltos</span></div>
                ${conAlerta > 0 ? `<div class="faltante-resumen-stat"><span class="faltante-resumen-num" style="color:#dc2626">${conAlerta}</span><span>⚠️ Alertas</span></div>` : ''}
            </div>`;
        } else {
            faltantesBody.innerHTML = '';
        }

        // Ordenar: alertas primero, luego faltante, en_gestion, resuelto
        const ordenEstado = { faltante: 0, en_gestion: 1, resuelto: 2 };
        const sorted = [...data].sort((a, b) => {
            const aAlert = alertaFaltante(a) ? -1 : 0;
            const bAlert = alertaFaltante(b) ? -1 : 0;
            if (aAlert !== bAlert) return aAlert - bAlert;
            return (ordenEstado[a.estado] ?? 9) - (ordenEstado[b.estado] ?? 9);
        });

        faltantesBody.innerHTML += sorted.map(f => buildFaltanteCard(f, tipo)).join('');

        // Eventos: cambio de estado directo
        faltantesBody.querySelectorAll('.faltante-btn-accion[data-estado]').forEach(btn => {
            btn.addEventListener('click', () => {
                const estado = btn.dataset.estado;
                if (estado === 'resuelto') {
                    document.getElementById(`resolve-form-${btn.dataset.id}`).classList.remove('hidden');
                    document.getElementById(`acciones-${btn.dataset.id}`).classList.add('hidden');
                } else {
                    cambiarEstadoFaltante(btn.dataset.id, estado);
                }
            });
        });

        // Abrir formulario "En gestión" con nota opcional
        faltantesBody.querySelectorAll('.trigger-gestion').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById(`gestion-form-${btn.dataset.id}`).classList.remove('hidden');
                document.getElementById(`acciones-${btn.dataset.id}`).classList.add('hidden');
            });
        });

        // Confirmar "En gestión" con nota
        faltantesBody.querySelectorAll('.confirm-gestion').forEach(btn => {
            btn.addEventListener('click', () => {
                const form = document.getElementById(`gestion-form-${btn.dataset.id}`);
                const nota = form.querySelector('.faltante-nota-gestion-input').value.trim() || null;
                cambiarEstadoFaltante(btn.dataset.id, 'en_gestion', null, nota);
            });
        });

        // Cancelar "En gestión"
        faltantesBody.querySelectorAll('.cancel-gestion').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById(`gestion-form-${btn.dataset.id}`).classList.add('hidden');
                document.getElementById(`acciones-${btn.dataset.id}`).classList.remove('hidden');
            });
        });

        // Confirmar resolución con días
        faltantesBody.querySelectorAll('.confirm-resolve').forEach(btn => {
            btn.addEventListener('click', () => {
                const form = document.getElementById(`resolve-form-${btn.dataset.id}`);
                const dias = parseInt(form.querySelector('.faltante-dias-input').value) || null;
                cambiarEstadoFaltante(btn.dataset.id, 'resuelto', dias);
            });
        });

        // Cancelar resolución
        faltantesBody.querySelectorAll('.cancel-resolve').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById(`resolve-form-${btn.dataset.id}`).classList.add('hidden');
                document.getElementById(`acciones-${btn.dataset.id}`).classList.remove('hidden');
            });
        });

        // Confirmar recepción — jefe_deposito cierra el ticket
        faltantesBody.querySelectorAll('.btn-confirmar').forEach(btn => {
            btn.addEventListener('click', () => confirmarFaltante(btn.dataset.id));
        });

        // Eliminar
        faltantesBody.querySelectorAll('.btn-eliminar').forEach(btn => {
            btn.addEventListener('click', () => eliminarFaltante(btn.dataset.id));
        });

        actualizarBadgeFaltantes();
    } catch (e) {
        faltantesBody.innerHTML = '<p class="docs-msg error-msg">Error al conectar con el servidor.</p>';
    }
}

async function cambiarEstadoFaltante(id, estado, diasEntrega = null, notaGestion = null) {
    try {
        const body = { estado };
        if (diasEntrega !== null) body.dias_entrega = diasEntrega;
        if (notaGestion !== null) body.nota_gestion = notaGestion;
        const res = await fetch(`${BASE_URL}/api/faltantes/${id}`, {
            method:      'PATCH',
            credentials: 'include',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify(body),
        });
        if (res.ok) loadFaltantes();
    } catch (e) {}
}

async function confirmarFaltante(id) {
    if (!confirm('¿Confirmás que el producto llegó al depósito? El ticket se cerrará.')) return;
    try {
        const res = await fetch(`${BASE_URL}/api/faltantes/${id}/confirmar`, {
            method: 'PATCH', credentials: 'include',
        });
        if (res.ok) loadFaltantes();
    } catch (e) {}
}

async function eliminarFaltante(id) {
    if (!confirm('¿Eliminar este faltante?')) return;
    try {
        const res = await fetch(`${BASE_URL}/api/faltantes/${id}`, {
            method: 'DELETE', credentials: 'include',
        });
        if (res.ok) loadFaltantes();
    } catch (e) {}
}

faltanteSubmitBtn.addEventListener('click', async () => {
    const producto = faltanteProductoInput.value.trim();
    const nota     = faltanteNotaInput.value.trim();
    if (!producto) {
        mostrarDocMsg(faltanteSubmitMsg, 'Ingresá el nombre del producto.', 'error');
        return;
    }
    faltanteSubmitBtn.disabled    = true;
    faltanteSubmitBtn.textContent = 'Guardando...';
    faltanteSubmitMsg.classList.add('hidden');
    try {
        const res  = await fetch(`${BASE_URL}/api/faltantes`, {
            method:      'POST',
            credentials: 'include',
            headers:     { 'Content-Type': 'application/json' },
            body:        JSON.stringify({ producto, nota }),
        });
        const data = await res.json();
        if (res.ok) {
            mostrarDocMsg(faltanteSubmitMsg, '✅ Faltante reportado.', 'ok');
            faltanteProductoInput.value = '';
            faltanteNotaInput.value     = '';
            loadFaltantes();
        } else {
            mostrarDocMsg(faltanteSubmitMsg, data.error || 'Error al guardar.', 'error');
        }
    } catch (e) {
        mostrarDocMsg(faltanteSubmitMsg, 'Error al conectar con el servidor.', 'error');
    } finally {
        faltanteSubmitBtn.disabled    = false;
        faltanteSubmitBtn.textContent = 'Reportar faltante';
    }
});

// ── Init ───────────────────────────────────────────────────────────────────────
checkSession();
