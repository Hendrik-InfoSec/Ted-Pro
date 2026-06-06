function toggleRow(id) {
  var el = document.getElementById('detail-' + id);
  var arrow = document.getElementById('arrow-' + id);
  if (!el) return;
  el.classList.toggle('open');
  if (arrow) arrow.style.transform = el.classList.contains('open') ? 'rotate(90deg)' : 'rotate(0deg)';
}

function qtyEdit(pid, current) {
  var cell = document.getElementById('qty-display-' + pid);
  if (!cell) return;
  cell.innerHTML =
    '<input id="qty-input-' + pid + '" type="number" min="0" value="' + current + '" ' +
    'style="width:70px;padding:3px 6px;border:1px solid #FFD5A5;border-radius:6px;font-size:13px;font-family:inherit" ' +
    'onclick="event.stopPropagation()">' +
    '<button onclick="event.stopPropagation();qtySave(\'' + pid + '\')" ' +
    'style="margin-left:6px;padding:3px 10px;background:#FF922B;color:white;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer">Save</button>' +
    '<button onclick="event.stopPropagation();qtyCancel(\'' + pid + '\',' + current + ')" ' +
    'style="margin-left:4px;padding:3px 8px;background:white;color:#8B6914;border:1px solid #FFD5A5;border-radius:6px;font-size:12px;cursor:pointer">Cancel</button>';
}

function qtySave(pid) {
  var input = document.getElementById('qty-input-' + pid);
  if (!input) return;
  var val = parseInt(input.value);
  if (isNaN(val) || val < 0) { alert('Please enter a valid number'); return; }
  fetch('/admin/products/' + pid + '/update-qty', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    credentials: 'same-origin',
    body: 'qty=' + val
  }).then(function(r) { return r.text(); }).then(function(html) {
    var cell = document.getElementById('qty-display-' + pid);
    if (cell) cell.outerHTML = html;
  }).catch(function(e) { alert('Save failed: ' + e.message); });
}

function qtyCancel(pid, original) {
  var cell = document.getElementById('qty-display-' + pid);
  if (!cell) return;
  cell.innerHTML = original + ' units ' +
    '<button onclick="event.stopPropagation();qtyEdit(\'' + pid + '\',' + original + ')" ' +
    'style="font-size:11px;color:#FF922B;text-decoration:underline;background:none;border:none;cursor:pointer">edit</button>';
}
