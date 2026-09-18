'use strict';
document.querySelector('[data-voltar]')?.addEventListener('click', () => history.back());
const tipo = document.querySelector('#tipo');
function atualizarTipo() {
  document.querySelectorAll('[data-tipos]').forEach(section => {
    const visible = section.dataset.tipos.split(' ').includes(tipo.value);
    section.hidden = !visible;
    section.querySelectorAll('input,select,button').forEach(input => { input.disabled = !visible; });
  });
  document.querySelectorAll('[data-categoria]').forEach(option => {
    option.hidden = option.disabled = option.dataset.categoria !== (tipo.value === 'entrada' ? 'receita' : 'despesa');
    if (option.disabled && option.selected) option.parentElement.value = '';
  });
}
if (tipo) { tipo.addEventListener('change', atualizarTipo); atualizarTipo(); }
const papel = document.querySelector('#papel');
function atualizarPapel() {
  document.querySelectorAll('[data-papel]').forEach(section => { section.hidden = section.dataset.papel !== papel.value; });
}
if (papel) { papel.addEventListener('change', atualizarPapel); atualizarPapel(); }
document.querySelectorAll('[data-rateios]').forEach(section => {
  const partes = section.querySelector('[data-partes]');
  const mensagem = section.querySelector('[data-rateio-mensagem]');
  function adicionarParte() {
    const nova = partes.firstElementChild.cloneNode(true);
    nova.querySelectorAll('input,select').forEach(input => { input.value = ''; });
    partes.append(nova);
  }
  section.querySelector('[data-adicionar]').addEventListener('click', adicionarParte);
  section.querySelector('[data-dividir]').addEventListener('click', () => {
    const total = section.closest('form').querySelector('[name="valor"]');
    const texto = total.value.trim();
    if (!/^\d{1,11}(?:[.,]\d{1,2})?$/.test(texto)) {
      mensagem.textContent = 'Informe primeiro o valor total, como 100,00, sem separador de milhar.';
      total.focus();
      return;
    }
    const [inteiro, decimal = ''] = texto.split(/[.,]/);
    const centavos = Number(inteiro) * 100 + Number(decimal.padEnd(2, '0'));
    if (centavos < 2 || centavos > 1000000000000) {
      mensagem.textContent = 'Para dividir, o total deve ser de pelo menos R$ 0,02 e estar dentro do limite permitido.';
      total.focus();
      return;
    }
    if (partes.children.length > 2) {
      mensagem.textContent = 'Remova as partes extras para dividir entre apenas dois responsáveis.';
      return;
    }
    if (partes.children.length === 1) adicionarParte();
    const segunda = Math.floor(centavos / 2);
    [centavos - segunda, segunda].forEach((valor, index) => {
      partes.children[index].querySelector('[name="parte[]"]').value =
        `${Math.floor(valor / 100)},${String(valor % 100).padStart(2, '0')}`;
    });
    mensagem.textContent = 'Valor dividido. Confira o responsável de cada parte.' +
      (centavos % 2 ? ' O centavo restante ficou na primeira parte.' : '');
  });
  partes.addEventListener('click', event => {
    if (!event.target.matches('[data-remover]')) return;
    if (partes.children.length > 1) event.target.closest('[data-parte]').remove();
    else partes.querySelectorAll('input,select').forEach(input => { input.value = ''; });
  });
});
