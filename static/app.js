function copiar(id) {
  const el = document.getElementById(id);
  navigator.clipboard.writeText(el.value).then(() => {
    el.classList.add("copiado");
    setTimeout(() => el.classList.remove("copiado"), 800);
  });
}

function adicionarGrupo() {
  const box = document.getElementById("grupos");
  const i = box.querySelectorAll(".grupo").length;
  const div = document.createElement("div");
  div.className = "grupo";
  div.innerHTML = `<label>Grupo ${i + 1} <input name="grupo_nome_${i}" placeholder="nome do tópico"></label>
    <textarea name="grupo_termos_${i}" rows="6" class="mono"></textarea>`;
  box.appendChild(div);
}

function decidir(valor) {
  const form = document.getElementById("form-decisao");
  if (!form) return;
  if (valor === "excluir" && !form.querySelector('input[name="criterios"]:checked')) {
    alert("Para excluir, marque ao menos um critério.");
    return;
  }
  document.getElementById("decisao").value = valor;
  form.submit();
}

document.addEventListener("keydown", (ev) => {
  if (!document.getElementById("form-decisao")) return;
  const t = ev.target.tagName;
  if (t === "INPUT" && ev.target.type !== "checkbox" || t === "TEXTAREA" || t === "SELECT") return;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const k = ev.key.toLowerCase();
  if (k === "i") decidir("incluir");
  else if (k === "e") decidir("excluir");
  else if (k === "d") decidir("duvida");
  else if (ev.key === "ArrowRight" && document.getElementById("prox")) location = document.getElementById("prox").href;
  else if (ev.key === "ArrowLeft" && document.getElementById("ant")) location = document.getElementById("ant").href;
});

function acompanhar(url, chave, alvoId) {
  const alvo = document.getElementById(alvoId);
  if (!alvo) return;
  let estavaAtiva = !alvo.hidden;
  const tick = async () => {
    try {
      const r = await fetch(url);
      const s = (await r.json())[chave] || {};
      if (s.ativa) {
        estavaAtiva = true;
        alvo.hidden = false;
        const n = s.feitos ?? s.n ?? 0, t = s.total ?? 0;
        alvo.querySelector("span").textContent = `${n} de ${t || "?"}${s.base ? " · " + s.base : ""}${s.achados !== undefined ? " · " + s.achados + " resumos encontrados" : ""}`;
      } else if (estavaAtiva) {
        location.reload();
        return;
      }
    } catch (e) { /* servidor reiniciando */ }
    setTimeout(tick, 2500);
  };
  tick();
}
