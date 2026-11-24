const amman = [31.972, 35.902];
const tileOptions = {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'};
const tileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

function icons() {
    window.lucide?.createIcons?.();
}

function makeMap(element, center, zoom) {
    const map = L.map(element, {scrollWheelZoom: true, worldCopyJump: true, zoomControl: false}).setView(center, zoom);
    L.control.zoom({position: 'bottomleft', zoomInTitle: 'تكبير', zoomOutTitle: 'تصغير'}).addTo(map);
    const tiles = L.tileLayer(tileUrl, tileOptions).addTo(map);
    return {map, tiles};
}

function node(tag, className, content) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (content !== undefined) result.textContent = content;
    return result;
}

function storeIcon(color) {
    const pin = node('span', 'store-pin');
    pin.style.setProperty('--category', color);
    pin.append(node('b', ''));
    return L.divIcon({html: pin, className: 'pin-icon', iconSize: [34, 40], iconAnchor: [17, 36], popupAnchor: [0, -32]});
}

function storeCard(store, popup = false) {
    const article = node('article', popup ? 'map-popup' : 'store-card');
    const label = node('span', 'store-category', store.category);
    label.style.setProperty('--category', store.color);
    article.append(label, node('h3', '', store.name), node('p', 'muted', store.address));
    if (store.distance !== undefined) article.append(node('span', 'distance', `${store.distance} كم`));
    if (store.offer) article.append(node('p', 'offer', store.offer));
    const footer = node('div', 'inset');
    const link = node('a', 'text-link', 'التفاصيل');
    link.href = store.url;
    footer.append(node('span', 'muted', `${store.rewards} مكافآت`), link);
    article.append(footer);
    return article;
}

function explorer(root) {
    const {map, tiles} = makeMap(root, amman, 12);
    const layer = L.layerGroup().addTo(map);
    const status = document.querySelector('#map-status');
    const list = document.querySelector('#results');
    const count = document.querySelector('#count');
    const search = document.querySelector('#search');
    const locate = document.querySelector('#locate');
    let location = null;
    let category = '';
    let controller;
    let timer;
    let tileError = false;
    let visibleStores = '';
    let fitChallenge = Boolean(root.dataset.challenge);

    function mapMessage(message) {
        status.hidden = !message;
        status.textContent = message;
    }

    let tileTimer;
    tiles.on('tileerror', () => {
        tileError = true;
        clearTimeout(tileTimer);
        tileTimer = setTimeout(() => mapMessage('تعذّر تحميل بعض أجزاء الخريطة. قائمة المتاجر متاحة.'), 600);
    });
    tiles.on('loading', () => { tileError = false; clearTimeout(tileTimer); });
    tiles.on('load', () => { if (!tileError) mapMessage(''); });

    function draw(stores) {
        const signature = JSON.stringify(stores);
        if (signature === visibleStores) return;
        visibleStores = signature;
        list.replaceChildren();
        layer.clearLayers();
        count.textContent = `${stores.length} متجر`;
        if (!stores.length) list.append(node('p', 'muted empty', 'ما في متاجر مطابقة ضمن المنطقة الظاهرة. وسّع الخريطة أو غيّر البحث.'));
        for (const store of stores) {
            const marker = L.marker([store.latitude, store.longitude], {icon: storeIcon(store.color), title: store.name, alt: store.name});
            marker.bindPopup(storeCard(store, true)).addTo(layer);
            const card = storeCard(store);
            const focus = node('button', 'icon-button map-focus', '⌖');
            focus.type = 'button';
            focus.setAttribute('aria-label', 'اعرض ' + store.name + ' على الخريطة');
            focus.addEventListener('click', () => marker.openPopup());
            marker.on('popupopen', () => {
                list.querySelector('.selected')?.classList.remove('selected');
                card.classList.add('selected');
                if (list.scrollHeight > list.clientHeight) list.scrollTop = card.offsetTop - list.offsetTop;
            });
            marker.on('popupclose', () => card.classList.remove('selected'));
            card.querySelector('.inset').append(focus);
            list.append(card);
        }
    }

    async function load() {
        controller?.abort();
        const fetchState = new AbortController();
        controller = fetchState;
        list.setAttribute('aria-busy', 'true');
        const bounds = map.getBounds();
        const wraps = bounds.getEast() - bounds.getWest() >= 360;
        const params = new URLSearchParams({
            south: Math.max(-90, bounds.getSouth()), north: Math.min(90, bounds.getNorth()),
            west: wraps ? -180 : L.Util.wrapNum(bounds.getWest(), [-180, 180], true),
            east: wraps ? 180 : L.Util.wrapNum(bounds.getEast(), [-180, 180], true),
            q: search.value.trim(), category, challenge: root.dataset.challenge,
        });
        if (fitChallenge) {
            for (const name of ['south', 'north', 'west', 'east']) params.delete(name);
        }
        if (location) {
            params.set('lat', location.lat);
            params.set('lng', location.lng);
        }
        try {
            const response = await fetch(root.dataset.url + '?' + params, {signal: fetchState.signal});
            if (!response.ok) throw new Error('Map request failed');
            const stores = await response.json();
            if (controller !== fetchState) return;
            const shouldFit = fitChallenge && stores.length;
            fitChallenge = false;
            draw(stores);
            if (shouldFit) {
                map.fitBounds(stores.map(store => [store.latitude, store.longitude]), {padding: [35, 35], maxZoom: 15});
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                count.textContent = '';
                visibleStores = '';
                layer.clearLayers();
                list.replaceChildren(node('p', 'muted empty', 'تعذّر تحميل المتاجر. حاول مرة ثانية.'));
                const retry = node('button', 'btn outline', 'إعادة التحميل');
                retry.addEventListener('click', load);
                list.append(retry);
            }
        } finally {
            if (controller === fetchState) list.setAttribute('aria-busy', 'false');
        }
    }

    document.querySelectorAll('[data-category]').forEach(button => button.addEventListener('click', () => {
        document.querySelector('[data-category].active').classList.remove('active');
        document.querySelector('[aria-pressed="true"][data-category]').setAttribute('aria-pressed', 'false');
        button.classList.add('active');
        button.setAttribute('aria-pressed', 'true');
        category = button.dataset.category;
        load();
    }));
    search.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(load, 240);
    });
    map.on('moveend', load);
    let locationCircle;
    locate.addEventListener('click', () => {
        if (!navigator.geolocation) {
            mapMessage('الموقع غير متاح في هذا المتصفح. تقدر تكمل باستخدام الخريطة.');
            return;
        }
        locate.disabled = true;
        mapMessage('جارٍ تحديد موقعك…');
        navigator.geolocation.getCurrentPosition(position => {
            location = L.latLng(position.coords.latitude, position.coords.longitude);
            locationCircle?.remove();
            locationCircle = L.circleMarker(location, {radius: 9, weight: 3, color: '#fff', fillColor: '#2863ef', fillOpacity: 1}).addTo(map).bindTooltip('موقعك');
            map.setView(location, 14);
            mapMessage('');
            locate.disabled = false;
            load();
        }, () => {
            mapMessage('تعذّر تحديد موقعك. استخدم البحث أو حرّك الخريطة يدويّاً.');
            locate.disabled = false;
        }, {timeout: 10000, maximumAge: 60000});
    });
    new ResizeObserver(() => map.invalidateSize({debounceMoveend: true})).observe(root);
    load();
}

function locationPicker(root) {
    const form = root.closest('form');
    const lat = form.elements.latitude;
    const lng = form.elements.longitude;
    const position = lat.value && lng.value ? [Number(lat.value), Number(lng.value)] : null;
    const {map} = makeMap(root, position || amman, position ? 15 : 12);
    let marker;
    function update(value) {
        if (!marker) marker = L.marker(value, {icon: storeIcon('#25876d')}).addTo(map);
        else marker.setLatLng(value);
    }
    if (position) update(position);
    map.on('click', event => {
        lat.value = event.latlng.lat.toFixed(6);
        lng.value = L.Util.wrapNum(event.latlng.lng, [-180, 180], true).toFixed(6);
        update([Number(lat.value), Number(lng.value)]);
    });
    function sync() {
        if (lat.value && lng.value && lat.validity.valid && lng.validity.valid) {
            const value = [Number(lat.value), Number(lng.value)];
            update(value);
            map.panTo(value);
        }
    }
    lat.addEventListener('change', sync);
    lng.addEventListener('change', sync);
    new ResizeObserver(() => map.invalidateSize()).observe(root);
}

function purchaseCode() {
    const match = location.hash.match(/^#([a-f0-9]{64})$/);
    const field = document.querySelector('#purchase-token');
    if (match) {
        try { sessionStorage.setItem('purchase-token', match[1]); } catch {}
        history.replaceState(null, '', location.pathname + location.search);
    }
    if (!field) return;
    if (match) field.value = match[1];
    try {
        field.value ||= sessionStorage.getItem('purchase-token') || '';
        field.form.addEventListener('submit', () => sessionStorage.removeItem('purchase-token'));
    } catch {}
}

icons();
const mapRoot = document.querySelector('#map');
if (mapRoot) explorer(mapRoot);
document.querySelectorAll('.location-picker').forEach(locationPicker);
if (document.querySelector('#confirm-purchase')) purchaseCode();
