# Interface de acompanhamento

Referência visual: `dashboard-concept.png`, criada com o Image Gen integrado.

Brief: painel desktop completo em português para Job Hunter AI, aplicação local;
sidebar branca de 272px, fundo frio claro, azul vivo, tipografia sans, navegação
Visão geral / Vagas / Currículo / Candidaturas / Atividade / Integrações. Cabeçalho
'Sua próxima oportunidade', métricas do banco, botão 'Executar demonstração',
tabela de três vagas de exemplo, busca e filtro por situação. Dois painéis inferiores
para o currículo principal e atividade recente. Sem hero de marketing, gradientes,
fotografias, métricas inventadas ou controles sem ação. Todos os textos e controles
são nativos no frontend. Fonte visual Segoe UI/Inter, superfícies brancas, bordas
sutis, raios entre 7 e 11px, ícones lineares.

Tokens: fundo #F5F7FC, superfície #FFFFFF, texto #10162A, texto secundário #5A6478,
primária #1357F4, borda #D8DFEB. Layout principal com sidebar fixa e conteúdo fluido;
a tela móvel usa menu recolhido, métricas 2x2 e lista de oportunidades adaptada.

A referência é a especificação de layout, não a fonte dos dados. Score e timestamps
vêm do backend. Em particular, a vaga Demo Unknown tem 40 pontos no perfil sintético,
embora a referência ilustrativa mostre 20. A informação correta do banco prevalece.
Os estados secundários mantêm tokens e componentes da tela principal.

As capturas de QA ficam fora do repositório. A referência visual não contém dados
pessoais nem credenciais. O projeto é servido pelo Flask/Docker e não foi publicado
em um serviço externo.
