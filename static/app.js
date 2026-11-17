const texto = document.getElementById("textoEntrada");
const statusEl = document.getElementById("status");
const vozSelect = document.getElementById("voz");
let vozes = [];

function status(message) {
  statusEl.textContent = message;
}

function carregarVozes() {
  if (!("speechSynthesis" in window)) return;
  vozes = speechSynthesis.getVoices();
  vozSelect.innerHTML = '<option value="">Voz padrão do dispositivo</option>';

  vozes.forEach((voz, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${voz.name} (${voz.lang})`;
    vozSelect.appendChild(option);
  });

  const pt = vozes.findIndex(v => /^pt(-|_)/i.test(v.lang));
  if (pt >= 0) vozSelect.value = String(pt);
}

if ("speechSynthesis" in window) {
  carregarVozes();
  speechSynthesis.onvoiceschanged = carregarVozes;
} else {
  status("Este navegador não oferece leitura em voz alta. Experimente uma versão atualizada do Chrome ou Edge.");
}

function dividirEmPartes(conteudo, limite = 2200) {
  const frases = conteudo.match(/[^.!?]+[.!?]+[\s]*/g) || [conteudo];
  const partes = [];
  let atual = "";

  for (const frase of frases) {
    if ((atual + frase).length > limite && atual) {
      partes.push(atual.trim());
      atual = "";
    }

    if (frase.length > limite) {
      for (let i = 0; i < frase.length; i += limite) {
        if (atual) {
          partes.push(atual.trim());
          atual = "";
        }
        partes.push(frase.slice(i, i + limite).trim());
      }
    } else {
      atual += frase;
    }
  }

  if (atual.trim()) partes.push(atual.trim());
  return partes.filter(Boolean);
}

document.getElementById("ouvirBtn").addEventListener("click", () => {
  const conteudo = texto.value.trim();
  if (!conteudo) return status("Digite ou cole um texto antes de iniciar a leitura.");
  if (!("speechSynthesis" in window)) {
    return status("Leitura em voz alta não disponível neste navegador.");
  }

  speechSynthesis.cancel();
  const partes = dividirEmPartes(conteudo);
  partes.forEach((parte, index) => {
    const fala = new SpeechSynthesisUtterance(parte);
    fala.lang = "pt-BR";
    fala.rate = Number(document.getElementById("velocidade").value);
    fala.pitch = Number(document.getElementById("tom").value);

    const selecionada = vozSelect.value;
    if (selecionada !== "" && vozes[Number(selecionada)]) {
      fala.voice = vozes[Number(selecionada)];
    }

    if (index === partes.length - 1) {
      fala.onend = () => status("Leitura concluída.");
    }
    fala.onerror = () => status("O navegador encontrou um problema durante a leitura.");
    speechSynthesis.speak(fala);
  });

  status("Leitura em andamento.");
});

document.getElementById("pausarBtn").addEventListener("click", () => {
  if (!("speechSynthesis" in window)) return;
  if (speechSynthesis.paused) {
    speechSynthesis.resume();
    status("Leitura retomada.");
  } else if (speechSynthesis.speaking) {
    speechSynthesis.pause();
    status("Leitura pausada.");
  }
});

document.getElementById("pararBtn").addEventListener("click", () => {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  status("Leitura interrompida.");
});

document.getElementById("limparBtn").addEventListener("click", () => {
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  texto.value = "";
  status("Texto apagado.");
});

document.getElementById("extrairBtn").addEventListener("click", async () => {
  const url = document.getElementById("urlEntrada").value.trim();
  if (!url) return status("Informe o endereço da página.");

  const button = document.getElementById("extrairBtn");
  button.disabled = true;
  button.textContent = "Extraindo...";
  status("Aguarde enquanto tentamos extrair o texto da página.");

  try {
    const response = await fetch("/api/extrair", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url})
    });
    const data = await response.json();

    if (!response.ok) throw new Error(data.error || "Não foi possível extrair o texto.");

    texto.value = data.text;
    const aviso = data.truncated
      ? " O conteúdo foi limitado para manter o desempenho."
      : "";
    const metodo = data.method ? ` Método: ${data.method}.` : "";
    status(`Texto extraído. Revise antes de ouvir.${aviso}${metodo}`);
  } catch (error) {
    status(error.message || "Falha na extração. Você pode colar o texto manualmente.");
  } finally {
    button.disabled = false;
    button.textContent = "Extrair texto";
  }
});

for (const [id, outputId] of [
  ["velocidade", "velocidadeValor"],
  ["tom", "tomValor"],
  ["tamanho", "tamanhoValor"]
]) {
  const input = document.getElementById(id);
  const output = document.getElementById(outputId);
  input.addEventListener("input", () => {
    output.value = input.value;
    if (id === "tamanho") texto.style.fontSize = `${input.value}px`;
  });
}

document.getElementById("espacamento").addEventListener("change", event => {
  texto.style.lineHeight = event.target.value;
});

document.getElementById("altoContraste").addEventListener("change", event => {
  document.body.classList.toggle("high-contrast", event.target.checked);
});

document.getElementById("fonteLegivel").addEventListener("change", event => {
  texto.classList.toggle("readable-font", event.target.checked);
});
