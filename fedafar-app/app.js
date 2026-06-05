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

    // Carrito: visible para cliente, jefe, admin — oculto para empleado
    if (tipo === 'empleado') {
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

    // Documentos: empleado, jefe, admin
    if (tipo === 'empleado' || tipo === 'jefe' || tipo === 'admin') {
        docsBtn.classList.remove('hidden');
    } else {
        docsBtn.classList.add('hidden');
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
    const labels = { 'cta-cte': 'Cta. Cte.', 'empleado': 'Empleado', 'contado': 'Contado', 'jefe': 'Jefe', 'admin': 'Admin' };
    const colors = { 'cta-cte': '#7c3aed', 'empleado': '#e07b00', 'contado': '#28a745', 'jefe': '#db2777', 'admin': '#dc2626' };
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
        const verDual    = tipo === 'empleado' || tipo === 'jefe' || tipo === 'admin';
        const conCarrito = tipo !== 'empleado';

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
            html += `
                <tr>
                    <td><strong>${row.nombre}</strong></td>
                    <td style="text-align:center">${row.comprobantes_pendientes}</td>
                    <td class="${saldoClass}">$ ${saldo.toLocaleString('es-AR', {minimumFractionDigits:2})}</td>
                </tr>
            `;
        });
        html += '</tbody></table>';
        todasCuentasBody.innerHTML = html;

    } catch (e) {
        todasCuentasBody.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar.</p>';
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

// ── Documentos de empleados ────────────────────────────────────────────────────

const TIPO_LABEL = { recibo_sueldo: 'Recibo de Sueldo', art_tarjeta: 'Tarjeta ART', otro: 'Otro' };

docsBtn.addEventListener('click', () => openDocsModal());
closeDocsBtn.addEventListener('click', () => docsModal.classList.add('hidden'));
backFromDocs.addEventListener('click',  () => docsModal.classList.add('hidden'));

async function openDocsModal() {
    docsModal.classList.remove('hidden');
    const tipo = currentUser?.tipo_precio;
    const esGestor = tipo === 'jefe' || tipo === 'admin';

    docsModalTitle.textContent = esGestor ? '📁 Gestión de Documentos' : '📄 Mis Documentos';
    docsUploadSection.classList.toggle('hidden', !esGestor);

    if (esGestor) {
        await cargarEmpleadosSelector();
    }
    await loadDocs();
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

async function loadDocs() {
    docsBody.innerHTML = '<p style="text-align:center;padding:20px;color:var(--text-muted);">Cargando...</p>';
    try {
        const res  = await fetch(`${BASE_URL}/api/docs`, { credentials: 'include' });
        const data = await res.json();

        if (!Array.isArray(data) || data.length === 0) {
            docsBody.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);">Sin documentos aún.</p>';
            return;
        }

        const miId = currentUser?.id;
        let html = '';
        data.forEach(doc => {
            const esFirmado   = doc.estado === 'firmado';
            const tipoLabel   = TIPO_LABEL[doc.tipo] || doc.tipo;
            const esMio       = String(doc.empleado_id) === String(miId);
            const estadoHtml  = esFirmado
                ? `<span class="doc-estado estado-firmado">✅ Firmado el ${doc.firma_timestamp?.substring(0, 10)} — ${doc.firma_nombre}</span>`
                : `<span class="doc-estado estado-pendiente">⏳ Pendiente de firma</span>`;

            html += `
                <div class="doc-card">
                    <div class="doc-info">
                        <span class="doc-tipo">${tipoLabel}</span>
                        <strong class="doc-nombre">${doc.nombre_archivo}</strong>
                        ${doc.periodo ? `<span class="doc-periodo">${doc.periodo}</span>` : ''}
                        ${estadoHtml}
                    </div>
                    <div class="doc-acciones">
                        <button class="doc-btn" onclick="descargarDoc('${doc.id}','${doc.nombre_archivo}')" title="Descargar">
                            <i data-lucide="download"></i>
                        </button>
                        ${!esFirmado && esMio ? `
                        <button class="doc-btn doc-btn--firmar" onclick="openSignPad('${doc.id}','${doc.nombre_archivo.replace(/'/g,'\\\'')}')" title="Firmar">
                            ✍️ Firmar
                        </button>` : ''}
                    </div>
                </div>`;
        });
        docsBody.innerHTML = html;
        lucide.createIcons();
    } catch (e) {
        docsBody.innerHTML = '<p style="text-align:center;color:red;padding:20px;">Error al cargar documentos.</p>';
    }
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

// Subida de documentos (admin / jefe)
docsFileInput.addEventListener('change', () => {
    docsFileName.textContent = docsFileInput.files[0]?.name || 'Ningún archivo seleccionado';
});

docsUploadBtn.addEventListener('click', async () => {
    const empleadoId = docsEmpleadoSel.value;
    const tipo       = docsTipoSel.value;
    const periodo    = docsPeriodoInput.value.trim();
    const file       = docsFileInput.files[0];

    docsUploadMsg.classList.add('hidden');

    if (!empleadoId) {
        mostrarDocMsg(docsUploadMsg, 'Seleccioná un empleado', 'error');
        return;
    }
    if (!file) {
        mostrarDocMsg(docsUploadMsg, 'Seleccioná un archivo PDF', 'error');
        return;
    }

    docsUploadBtn.disabled   = true;
    docsUploadBtn.textContent = 'Subiendo...';

    const fd = new FormData();
    fd.append('empleado_id', empleadoId);
    fd.append('tipo',        tipo);
    fd.append('periodo',     periodo);
    fd.append('archivo',     file);

    try {
        const res  = await fetch(`${BASE_URL}/api/docs/subir`, {
            method: 'POST', credentials: 'include', body: fd
        });
        const data = await res.json();
        if (res.ok && data.ok) {
            mostrarDocMsg(docsUploadMsg, '✅ Documento subido exitosamente', 'ok');
            docsFileInput.value     = '';
            docsFileName.textContent = 'Ningún archivo seleccionado';
            docsPeriodoInput.value  = '';
            await loadDocs();
        } else {
            mostrarDocMsg(docsUploadMsg, 'Error: ' + (data.error || 'desconocido'), 'error');
        }
    } catch (e) {
        mostrarDocMsg(docsUploadMsg, 'Error al conectar con el servidor', 'error');
    } finally {
        docsUploadBtn.disabled   = false;
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

// ── Init ───────────────────────────────────────────────────────────────────────
checkSession();
