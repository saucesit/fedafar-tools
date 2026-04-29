let PRODUCTS = [];
let cart = [];

// Initialize Lucide icons
lucide.createIcons();

// DOM Elements
const productGrid = document.getElementById('product-grid');
const searchInput = document.getElementById('product-search');
const cartBtn = document.getElementById('cart-btn');
const closeCartBtn = document.getElementById('close-cart');
const backToShopBtn = document.getElementById('back-to-shop');
const cartModal = document.getElementById('cart-modal');
const cartCount = document.getElementById('cart-count');
const cartItemsContainer = document.getElementById('cart-items');
const totalPriceEl = document.getElementById('total-price');
const sendOrderBtn = document.getElementById('send-order');
const categoryPills = document.querySelectorAll('.pill');

// Render Products
function renderProducts(filter = '', category = 'all') {
    productGrid.innerHTML = '';
    
    // PRODUCTS viene de products.js
    const filtered = PRODUCTS.filter(p => {
        const matchesSearch = p.name.toLowerCase().includes(filter.toLowerCase()) || 
                             p.lab.toLowerCase().includes(filter.toLowerCase());
        const matchesCat = category === 'all' || p.category === category;
        return matchesSearch && matchesCat;
    });

    filtered.forEach(product => {
        const card = document.createElement('div');
        card.className = 'product-card';
        card.innerHTML = `
            <div class="prod-info">
                <span class="prod-lab">${product.lab}</span>
                <h3>${product.name}</h3>
                <p class="prod-price">$ ${product.price.toLocaleString('es-AR')}</p>
            </div>
            <div class="prod-actions">
                <input type="number" id="qty-${product.id}" class="qty-input" value="1" min="1">
                <button class="add-btn" data-id="${product.id}">
                    Añadir
                </button>
            </div>
        `;
        productGrid.appendChild(card);
    });
    
    lucide.createIcons();
    
    // Add event listeners to buttons
    document.querySelectorAll('.add-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = parseInt(btn.dataset.id);
            const qtyInput = document.getElementById(`qty-${id}`);
            const qty = parseInt(qtyInput.value) || 1;
            addToCart(id, qty);
        });
    });
}

// Cart Logic
function addToCart(productId, qtyToAdd) {
    const product = PRODUCTS.find(p => p.id === productId);
    const existing = cart.find(item => item.id === productId);

    if (existing) {
        existing.qty += qtyToAdd;
    } else {
        cart.push({ ...product, qty: qtyToAdd });
    }
    
    // Feedback visual opcional
    const btn = document.querySelector(`.add-btn[data-id="${productId}"]`);
    if(btn) {
        btn.innerText = "¡Agregado!";
        setTimeout(() => btn.innerText = "Añadir", 1500);
    }
    
    updateCart();
}

function updateCart() {
    // Update count
    const totalQty = cart.reduce((sum, item) => sum + item.qty, 0);
    cartCount.innerText = totalQty;

    // Update list
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
    lucide.createIcons();

    // Event listeners para los controles del carrito
    document.querySelectorAll('.minus-btn').forEach(btn => {
        btn.addEventListener('click', (e) => updateItemQty(parseInt(btn.dataset.id), -1));
    });
    document.querySelectorAll('.plus-btn').forEach(btn => {
        btn.addEventListener('click', (e) => updateItemQty(parseInt(btn.dataset.id), 1));
    });
    document.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => removeItem(parseInt(btn.dataset.id)));
    });
}

function updateItemQty(productId, change) {
    const existing = cart.find(item => item.id === productId);
    if (existing) {
        existing.qty += change;
        if (existing.qty <= 0) {
            removeItem(productId);
        } else {
            updateCart();
        }
    }
}

function removeItem(productId) {
    cart = cart.filter(item => item.id !== productId);
    updateCart();
}

// Event Listeners
searchInput.addEventListener('input', (e) => {
    renderProducts(e.target.value);
});

categoryPills.forEach(pill => {
    pill.addEventListener('click', () => {
        categoryPills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        renderProducts(searchInput.value, pill.dataset.cat);
    });
});

cartBtn.addEventListener('click', () => cartModal.classList.remove('hidden'));
closeCartBtn.addEventListener('click', () => cartModal.classList.add('hidden'));
if(backToShopBtn) backToShopBtn.addEventListener('click', () => cartModal.classList.add('hidden'));

sendOrderBtn.addEventListener('click', () => {
    if (cart.length === 0) return alert("El carrito está vacío");

    let message = "📦 *NUEVO PEDIDO - FEDAFAR*\n\n";
    cart.forEach(item => {
        message += `• ${item.name} (${item.lab}) x${item.qty}\n`;
    });
    
    const total = totalPriceEl.innerText;
    message += `\n*TOTAL ESTIMADO:* ${total}`;
    message += `\n\n_Por favor confirmar stock y precios vigentes._`;

    const encoded = encodeURIComponent(message);
    window.open(`https://wa.me/5493876835525?text=${encoded}`);
});

// Fetch Products from API
async function fetchProducts() {
    try {
        productGrid.innerHTML = '<p style="text-align:center; width:100%;">Cargando catálogo en vivo...</p>';
        const response = await fetch('/api/productos');
        PRODUCTS = await response.json();
        renderProducts();
    } catch (error) {
        console.error("Error cargando productos:", error);
        productGrid.innerHTML = '<p style="text-align:center; color:red; width:100%;">Error al conectar con el servidor FEDAFAR. Asegúrese de que la API esté corriendo.</p>';
    }
}

// Initial Fetch
fetchProducts();
