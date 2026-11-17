const texto = document.getElementById("textoEntrada");
const statusEl = document.getElementById("status");
const vozSelect = document.getElementById("voz");
const botaoExtrair = document.getElementById("extrairBtn");
const resultadoInfo = document.getElementById("resultadoInfo");
const tituloPagina = document.getElementById("tituloPagina");
const detalhesExtracao = document.getElementById("detalhesExtracao");
const visuaisSection = document.getElementById("visuaisSection");
const listaVisuais = document.getElementById("listaVisuais");

let vozes = [];
let partesLeitura = [];

function status(message) {
  statusEl.textContent = message;
}

function carregarVozes() {
  if (!("speechSynthesis" in window)) return;

  vozes = speechSynthesis.getVoices();
  const vozAnterior = vozSelect.value;

  vozSelect.innerHTML = "";

  const padrao = document.createElement("option");
  padrao.value = "";
  padrao.textContent = "Voz padrão do dispositivo";
  vozSelect.appendChild(padrao);

  vozes.forEach((voz, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = `${voz.name} (${voz.lang})`;
    vozSelect.appendChild(option);
  });

  if (vozAnterior && vozes[Number(vozAnterior)]) {
    vozSelect.value = vozAnterior;
  } else {
    const pt = vozes.findIndex(v => /^pt(-|_)/i.test(v.lang));

    if (pt >= 0) {
      vozSelect.value = String(pt);
    }
  }
}

if ("speechSynthesis" in window) {
  carregarVozes();
  speechSynthesis.onvoiceschanged = carregarVozes;
} else {
  status(
    "Este navegador não oferece leitura em voz alta. Experimente uma versão atualizada do Chrome ou Edge."
  );
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

  if (atual.trim()) {
    partes.push(atual.trim());
  }

  return partes.filter(Boolean);
}

function mostrarImagens(imagens) {
  listaVisuais.replaceChildren();

  if (!Array.isArray(imagens) || imagens.length === 0) {
    visuaisSection.hidden = true;
    return;
  }

  imagens.forEach((imagem, indice) => {
    const item = document.createElement("li");

    const titulo = document.createElement("strong");
    titulo.textContent = `Elemento visual ${indice + 1}`;

    const descricao = document.createElement("p");
    descricao.textContent =
      imagem.description ||
      imagem.alt ||
      imagem.caption ||
      "Sem descrição textual disponível.";

    item.append(titulo, descricao);

    if (imagem.alt && imagem.caption && imagem.alt !== imagem.caption) {
      const complemento = document.createElement("p");
      complemento.className = "hint";
      complemento.textContent = `Texto alternativo: ${imagem.alt}`;
      item.appendChild(complemento);
    }

    listaVisuais.appendChild(item);
  });

  visuaisSection.hidden = false;
}

function mostrarInformacoes(data) {
  tituloPagina.textContent = data.title
    ? `Página: ${data.title}`
    : "Título da página não identificado.";

  const partes = [];

  if (data.method) {
    partes.push(`Método de extração: ${data.method}`);
  }

  if (Number.isInteger(data.table_count) && data.table_count > 0) {
    partes.push(`Tabelas identificadas: ${data.table_count}`);
  }

  if (Array.isArray(data.images)) {
    partes.push(
      `Elementos visuais com legenda ou texto alternativo: ${data.images.length}`
    );
  }

  if (data.truncated) {
    partes.push("O texto foi limitado para manter o desempenho.");
  }

  detalhesExtracao.textContent = partes.join(" • ");

  resultadoInfo.hidden = false;
  mostrarImagens(data.images || []);
}

document.getElementById("ouvirBtn").addEventListener("click", () => {
  const conteudo = texto.value.trim();

  if (!conteudo) {
    return status("Digite ou cole um texto antes de iniciar a leitura.");
  }

  if (!("speechSynthesis" in window)) {
    return status("Leitura em voz alta não disponível neste navegador.");
  }

  speechSynthesis.cancel();

  partesLeitura = dividirEmPartes(conteudo);

  partesLeitura.forEach((parte, index) => {
    const fala = new SpeechSynthesisUtterance(parte);

    fala.lang = "pt-BR";
    fala.rate = Number(document.getElementById("velocidade").value);
    fala.pitch = Number(document.getElementById("tom").value);

    const selecionada = vozSelect.value;

    if (selecionada !== "" && vozes[Number(selecionada)]) {
      fala.voice = vozes[Number(selecionada)];
    }

    if (index === partesLeitura.length - 1) {
      fala.onend = () => status("Leitura concluída.");
    }

    fala.onerror = () => {
      status("O navegador encontrou um problema durante a leitura.");
    };

    speechSynthesis.speak(fala);
  });

  status(
    `Leitura em andamento. ${partesLeitura.length} trecho(s) na fila.`
  );
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
  if ("speechSynthesis" in window) {
    speechSynthesis.cancel();
  }

  status("Leitura interrompida.");
});

document.getElementById("limparBtn").addEventListener("click", () => {
  if ("speechSynthesis" in window) {
    speechSynthesis.cancel();
  }

  texto.value = "";
  resultadoInfo.hidden = true;
  visuaisSection.hidden = true;
  listaVisuais.replaceChildren();

  status("Texto e informações da extração apagados.");
});

botaoExtrair.addEventListener("click", async () => {
  const url = document.getElementById("urlEntrada").value.trim();

  if (!url) {
    return status("Informe o endereço da página.");
  }

  botaoExtrair.disabled = true;
  botaoExtrair.textContent = "Extraindo...";

  status("Aguarde enquanto tentamos extrair o texto da página.");

  try {
    const response = await fetch("/api/extrair", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ url })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.error || "Não foi possível extrair o texto."
      );
    }

    texto.value = data.text || "";

    mostrarInformacoes(data);

    status("Texto extraído. Revise o conteúdo antes de ouvir.");

  } catch (error) {
    status(
      error.message ||
      "Falha na extração. Você pode colar o texto manualmente."
    );

  } finally {
    botaoExtrair.disabled = false;
    botaoExtrair.textContent = "Extrair texto";
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

    if (id === "tamanho") {
      texto.style.fontSize = `${input.value}px`;
    }
  });
}

document.getElementById("espacamento").addEventListener("change", event => {
  texto.style.lineHeight = event.target.value;
});

document.getElementById("altoContraste").addEventListener("change", event => {
  document.body.classList.toggle(
    "high-contrast",
    event.target.checked
  );
});

document.getElementById("fonteLegivel").addEventListener("change", event => {
  texto.classList.toggle(
    "readable-font",
    event.target.checked
  );
});