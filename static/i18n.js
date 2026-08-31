(function (global) {
    var LANG_KEY = "simust_lang";
    var SUPPORTED = ["en", "de", "es", "it"];

    var COUNTRY_CODES = [
        { code: "+49", label: "Germany (+49)" },
        { code: "+43", label: "Austria (+43)" },
        { code: "+41", label: "Switzerland (+41)" },
        { code: "+39", label: "Italy (+39)" },
        { code: "+34", label: "Spain (+34)" },
        { code: "+33", label: "France (+33)" },
        { code: "+44", label: "United Kingdom (+44)" },
        { code: "+31", label: "Netherlands (+31)" },
        { code: "+32", label: "Belgium (+32)" },
        { code: "+351", label: "Portugal (+351)" },
        { code: "+353", label: "Ireland (+353)" },
        { code: "+45", label: "Denmark (+45)" },
        { code: "+46", label: "Sweden (+46)" },
        { code: "+47", label: "Norway (+47)" },
        { code: "+48", label: "Poland (+48)" },
        { code: "+420", label: "Czechia (+420)" },
        { code: "+36", label: "Hungary (+36)" },
        { code: "+30", label: "Greece (+30)" },
        { code: "+90", label: "Turkey (+90)" },
        { code: "+1", label: "USA / Canada (+1)" },
        { code: "+52", label: "Mexico (+52)" },
        { code: "+54", label: "Argentina (+54)" },
        { code: "+55", label: "Brazil (+55)" },
        { code: "+56", label: "Chile (+56)" },
        { code: "+57", label: "Colombia (+57)" },
        { code: "+98", label: "Iran (+98)" },
        { code: "+971", label: "UAE (+971)" },
        { code: "+966", label: "Saudi Arabia (+966)" },
        { code: "+81", label: "Japan (+81)" },
        { code: "+82", label: "South Korea (+82)" },
        { code: "+86", label: "China (+86)" },
        { code: "+91", label: "India (+91)" },
        { code: "+61", label: "Australia (+61)" },
        { code: "+64", label: "New Zealand (+64)" },
        { code: "+27", label: "South Africa (+27)" },
        { code: "+234", label: "Nigeria (+234)" },
        { code: "+20", label: "Egypt (+20)" }
    ];

    var I18N = {
        en: {
            langEn: "English",
            langDe: "German",
            langEs: "Spanish",
            langIt: "Italian",
            publicWebsite: "Public website ↗",
            securePortal: "SECURE PORTAL",
            roleBasedAccess: "Role-based access to development data",
            kicker: "PRIVATE USER ENVIRONMENT",
            intro: "My SIMUST connects the player, parent, coach and academy to the information already collected inside the SIMUST application.",
            signIn: "Sign in",
            signInSub: "Enter your credentials to access your dashboard.",
            signInToAccount: "Sign in to your account",
            username: "Username",
            password: "Password",
            usernamePlaceholder: "e.g. player0142",
            signInBtn: "Sign In",
            noAccount: "Don't have an account? Register →",
            createAccount: "Create account",
            registerSub: "Register to access your role-based dashboard.",
            firstName: "First Name *",
            lastName: "Last Name *",
            age: "Age",
            gender: "Gender",
            male: "Male",
            female: "Female",
            other: "Other",
            club: "Club",
            team: "Team Name",
            personType: "Person Type *",
            player: "Player",
            coach: "Coach",
            academyManager: "Academy Manager",
            email: "Email *",
            emailPlaceholder: "e.g. name@email.com",
            phone: "Phone number *",
            phonePlaceholder: "Phone without country code",
            countryCode: "Country code *",
            profileImage: "Profile Image",
            imageLoaded: "Image loaded",
            registerBtn: "Register",
            backToSignIn: "← Back to sign in",
            fillRequired: "Please fill in all required fields (*).",
            passwordMin: "Password must be at least 4 characters.",
            invalidEmail: "Please enter a valid email address.",
            invalidPhone: "Please enter a phone number with country code.",
            registering: "Registering…",
            registerSuccess: "Registration successful! Please sign in.",
            accountCreated: "Account created! Please sign in.",
            registerFailed: "Registration failed.",
            networkError: "Network error. Is the backend running?",
            enterCredentials: "Please enter username and password.",
            signingIn: "Signing in…",
            invalidCredentials: "Invalid credentials.",
            forPlayerParent: "FOR PLAYER & PARENT",
            quote: "Results should start a better development conversation—not reduce a player to one score.",
            parentNote: "SIMUST makes changes in football behaviour visible. The coach connects those results to training, context and the individual player.",
            footer1: "PROTOTYPE · CONNECTED TO YOUR SIMUST DATA",
            footer2: "Privacy by role · Youth data protected",
            allRights: "© 2025 SIMUST. All rights reserved.",
            smartControl: "SMART CONTROL",
            results: "RESULTS",
            managePlayers: "MANAGE PLAYERS",
            logout: "Logout",
            live: "LIVE",
            idle: "IDLE",
            visualization: "Visualization",
            realtimePlay: "REALTIME PLAY",
            playing: "Playing…",
            stop: "Stop",
            showResults: "SHOW RESULTS ON SCREEN 2",
            trainingLevel: "Training Level",
            selectLevel: "Select Level",
            unlock: "Unlock",
            searchPlaceholder: "Search by SIMUST ID or Name...",
            selected: "SELECTED:",
            invalidLogin: "Invalid username or password"
        },
        de: {
            langEn: "Englisch",
            langDe: "Deutsch",
            langEs: "Spanisch",
            langIt: "Italienisch",
            publicWebsite: "Öffentliche Website ↗",
            securePortal: "SICHERES PORTAL",
            roleBasedAccess: "Rollenbasierter Zugriff auf Entwicklungsdaten",
            kicker: "PRIVATE BENUTZERUMGEBUNG",
            intro: "My SIMUST verbindet Spieler, Eltern, Trainer und Akademie mit den Informationen, die bereits in der SIMUST-Anwendung erfasst wurden.",
            signIn: "Anmelden",
            signInSub: "Geben Sie Ihre Zugangsdaten ein, um das Dashboard zu öffnen.",
            signInToAccount: "Melden Sie sich bei Ihrem Konto an",
            username: "Benutzername",
            password: "Passwort",
            usernamePlaceholder: "z. B. player0142",
            signInBtn: "Anmelden",
            noAccount: "Noch kein Konto? Registrieren →",
            createAccount: "Konto erstellen",
            registerSub: "Registrieren Sie sich für Ihr rollenbasiertes Dashboard.",
            firstName: "Vorname *",
            lastName: "Nachname *",
            age: "Alter",
            gender: "Geschlecht",
            male: "Männlich",
            female: "Weiblich",
            other: "Divers",
            club: "Verein",
            team: "Mannschaft",
            personType: "Personentyp *",
            player: "Spieler",
            coach: "Trainer",
            academyManager: "Akademie-Manager",
            email: "E-Mail *",
            emailPlaceholder: "z. B. name@email.com",
            phone: "Telefonnummer *",
            phonePlaceholder: "Nummer ohne Ländervorwahl",
            countryCode: "Ländervorwahl *",
            profileImage: "Profilbild",
            imageLoaded: "Bild geladen",
            registerBtn: "Registrieren",
            backToSignIn: "← Zurück zur Anmeldung",
            fillRequired: "Bitte füllen Sie alle Pflichtfelder (*) aus.",
            passwordMin: "Das Passwort muss mindestens 4 Zeichen haben.",
            invalidEmail: "Bitte geben Sie eine gültige E-Mail-Adresse ein.",
            invalidPhone: "Bitte geben Sie eine Telefonnummer mit Ländervorwahl ein.",
            registering: "Registrierung läuft…",
            registerSuccess: "Registrierung erfolgreich! Bitte anmelden.",
            accountCreated: "Konto erstellt! Bitte anmelden.",
            registerFailed: "Registrierung fehlgeschlagen.",
            networkError: "Netzwerkfehler. Läuft das Backend?",
            enterCredentials: "Bitte Benutzername und Passwort eingeben.",
            signingIn: "Anmeldung läuft…",
            invalidCredentials: "Ungültige Zugangsdaten.",
            forPlayerParent: "FÜR SPIELER & ELTERN",
            quote: "Ergebnisse sollen ein besseres Entwicklungsgespräch starten – nicht einen Spieler auf eine Zahl reduzieren.",
            parentNote: "SIMUST macht Veränderungen im Fußballverhalten sichtbar. Der Trainer verbindet diese Ergebnisse mit Training, Kontext und dem einzelnen Spieler.",
            footer1: "PROTOTYP · VERBUNDEN MIT IHREN SIMUST-DATEN",
            footer2: "Datenschutz nach Rolle · Jugenddaten geschützt",
            allRights: "© 2025 SIMUST. Alle Rechte vorbehalten.",
            smartControl: "SMART CONTROL",
            results: "ERGEBNISSE",
            managePlayers: "SPIELER VERWALTEN",
            logout: "Abmelden",
            live: "LIVE",
            idle: "BEREIT",
            visualization: "Visualisierung",
            realtimePlay: "ECHTZEIT-WIEDERGABE",
            playing: "Wiedergabe…",
            stop: "Stopp",
            showResults: "ERGEBNISSE AUF BILDSCHIRM 2 ZEIGEN",
            trainingLevel: "Trainingslevel",
            selectLevel: "Level wählen",
            unlock: "Freischalten",
            searchPlaceholder: "Suche nach SIMUST-ID oder Name...",
            selected: "AUSGEWÄHLT:",
            invalidLogin: "Ungültiger Benutzername oder Passwort"
        },
        es: {
            langEn: "Inglés",
            langDe: "Alemán",
            langEs: "Español",
            langIt: "Italiano",
            publicWebsite: "Sitio público ↗",
            securePortal: "PORTAL SEGURO",
            roleBasedAccess: "Acceso por rol a los datos de desarrollo",
            kicker: "ENTORNO PRIVADO DE USUARIO",
            intro: "My SIMUST conecta al jugador, los padres, el entrenador y la academia con la información ya recogida en la aplicación SIMUST.",
            signIn: "Iniciar sesión",
            signInSub: "Introduzca sus credenciales para acceder al panel.",
            signInToAccount: "Inicie sesión en su cuenta",
            username: "Usuario",
            password: "Contraseña",
            usernamePlaceholder: "p. ej. player0142",
            signInBtn: "Entrar",
            noAccount: "¿No tiene cuenta? Registrarse →",
            createAccount: "Crear cuenta",
            registerSub: "Regístrese para acceder a su panel según el rol.",
            firstName: "Nombre *",
            lastName: "Apellido *",
            age: "Edad",
            gender: "Género",
            male: "Masculino",
            female: "Femenino",
            other: "Otro",
            club: "Club",
            team: "Equipo",
            personType: "Tipo de persona *",
            player: "Jugador",
            coach: "Entrenador",
            academyManager: "Director de academia",
            email: "Correo electrónico *",
            emailPlaceholder: "p. ej. nombre@email.com",
            phone: "Teléfono *",
            phonePlaceholder: "Número sin código de país",
            countryCode: "Código de país *",
            profileImage: "Imagen de perfil",
            imageLoaded: "Imagen cargada",
            registerBtn: "Registrarse",
            backToSignIn: "← Volver al inicio de sesión",
            fillRequired: "Rellene todos los campos obligatorios (*).",
            passwordMin: "La contraseña debe tener al menos 4 caracteres.",
            invalidEmail: "Introduzca un correo electrónico válido.",
            invalidPhone: "Introduzca un teléfono con código de país.",
            registering: "Registrando…",
            registerSuccess: "Registro correcto. Inicie sesión.",
            accountCreated: "¡Cuenta creada! Inicie sesión.",
            registerFailed: "El registro ha fallado.",
            networkError: "Error de red. ¿Está el servidor en marcha?",
            enterCredentials: "Introduzca usuario y contraseña.",
            signingIn: "Iniciando sesión…",
            invalidCredentials: "Credenciales no válidas.",
            forPlayerParent: "PARA JUGADOR Y PADRES",
            quote: "Los resultados deben iniciar una mejor conversación de desarrollo, no reducir a un jugador a una puntuación.",
            parentNote: "SIMUST hace visibles los cambios en el comportamiento futbolístico. El entrenador conecta esos resultados con el entrenamiento, el contexto y el jugador.",
            footer1: "PROTOTIPO · CONECTADO A SUS DATOS SIMUST",
            footer2: "Privacidad por rol · Datos de jóvenes protegidos",
            allRights: "© 2025 SIMUST. Todos los derechos reservados.",
            smartControl: "SMART CONTROL",
            results: "RESULTADOS",
            managePlayers: "GESTIONAR JUGADORES",
            logout: "Cerrar sesión",
            live: "EN VIVO",
            idle: "INACTIVO",
            visualization: "Visualización",
            realtimePlay: "REPRODUCCIÓN EN TIEMPO REAL",
            playing: "Reproduciendo…",
            stop: "Detener",
            showResults: "MOSTRAR RESULTADOS EN PANTALLA 2",
            trainingLevel: "Nivel de entrenamiento",
            selectLevel: "Seleccionar nivel",
            unlock: "Desbloquear",
            searchPlaceholder: "Buscar por ID SIMUST o nombre...",
            selected: "SELECCIONADO:",
            invalidLogin: "Usuario o contraseña no válidos"
        },
        it: {
            langEn: "Inglese",
            langDe: "Tedesco",
            langEs: "Spagnolo",
            langIt: "Italiano",
            publicWebsite: "Sito pubblico ↗",
            securePortal: "PORTALE SICURO",
            roleBasedAccess: "Accesso in base al ruolo ai dati di sviluppo",
            kicker: "AMBIENTE UTENTE PRIVATO",
            intro: "My SIMUST collega giocatore, genitori, allenatore e accademia alle informazioni già raccolte nell'applicazione SIMUST.",
            signIn: "Accedi",
            signInSub: "Inserisci le credenziali per aprire la dashboard.",
            signInToAccount: "Accedi al tuo account",
            username: "Nome utente",
            password: "Password",
            usernamePlaceholder: "es. player0142",
            signInBtn: "Accedi",
            noAccount: "Non hai un account? Registrati →",
            createAccount: "Crea account",
            registerSub: "Registrati per accedere alla dashboard in base al ruolo.",
            firstName: "Nome *",
            lastName: "Cognome *",
            age: "Età",
            gender: "Genere",
            male: "Maschio",
            female: "Femmina",
            other: "Altro",
            club: "Club",
            team: "Squadra",
            personType: "Tipo di persona *",
            player: "Giocatore",
            coach: "Allenatore",
            academyManager: "Manager dell'accademia",
            email: "Email *",
            emailPlaceholder: "es. nome@email.com",
            phone: "Telefono *",
            phonePlaceholder: "Numero senza prefisso internazionale",
            countryCode: "Prefisso internazionale *",
            profileImage: "Immagine del profilo",
            imageLoaded: "Immagine caricata",
            registerBtn: "Registrati",
            backToSignIn: "← Torna all'accesso",
            fillRequired: "Compila tutti i campi obbligatori (*).",
            passwordMin: "La password deve avere almeno 4 caratteri.",
            invalidEmail: "Inserisci un indirizzo email valido.",
            invalidPhone: "Inserisci un telefono con prefisso internazionale.",
            registering: "Registrazione in corso…",
            registerSuccess: "Registrazione riuscita! Accedi.",
            accountCreated: "Account creato! Accedi.",
            registerFailed: "Registrazione non riuscita.",
            networkError: "Errore di rete. Il server è avviato?",
            enterCredentials: "Inserisci nome utente e password.",
            signingIn: "Accesso in corso…",
            invalidCredentials: "Credenziali non valide.",
            forPlayerParent: "PER GIOCATORE E GENITORI",
            quote: "I risultati devono avviare una conversazione di sviluppo migliore, non ridurre un giocatore a un punteggio.",
            parentNote: "SIMUST rende visibili i cambiamenti nel comportamento calcistico. L'allenatore collega quei risultati ad allenamento, contesto e giocatore.",
            footer1: "PROTOTIPO · COLLEGATO AI TUOI DATI SIMUST",
            footer2: "Privacy per ruolo · Dati dei giovani protetti",
            allRights: "© 2025 SIMUST. Tutti i diritti riservati.",
            smartControl: "SMART CONTROL",
            results: "RISULTATI",
            managePlayers: "GESTISCI GIOCATORI",
            logout: "Esci",
            live: "LIVE",
            idle: "INATTIVO",
            visualization: "Visualizzazione",
            realtimePlay: "RIPRODUZIONE IN TEMPO REALE",
            playing: "Riproduzione…",
            stop: "Stop",
            showResults: "MOSTRA RISULTATI SULLO SCHERMO 2",
            trainingLevel: "Livello di allenamento",
            selectLevel: "Seleziona livello",
            unlock: "Sblocca",
            searchPlaceholder: "Cerca per ID SIMUST o nome...",
            selected: "SELEZIONATO:",
            invalidLogin: "Nome utente o password non validi"
        }
    };

    function getLang() {
        try {
            var stored = localStorage.getItem(LANG_KEY);
            if (SUPPORTED.indexOf(stored) !== -1) return stored;
        } catch (e) {}
        return "en";
    }

    function setLang(lang) {
        if (SUPPORTED.indexOf(lang) === -1) lang = "en";
        try { localStorage.setItem(LANG_KEY, lang); } catch (e) {}
        applyI18n(lang);
        return lang;
    }

    function t(key, lang) {
        var code = lang || getLang();
        var dict = I18N[code] || I18N.en;
        if (dict[key]) return dict[key];
        return (I18N.en[key] || key);
    }

    function applyI18n(lang) {
        var code = lang || getLang();
        if (document.documentElement) document.documentElement.lang = code;
        var nodes = document.querySelectorAll("[data-i18n]");
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].textContent = t(nodes[i].getAttribute("data-i18n"), code);
        }
        var ph = document.querySelectorAll("[data-i18n-placeholder]");
        for (var j = 0; j < ph.length; j++) {
            ph[j].placeholder = t(ph[j].getAttribute("data-i18n-placeholder"), code);
        }
        var buttons = document.querySelectorAll(".lang-btn[data-lang]");
        for (var k = 0; k < buttons.length; k++) {
            if (buttons[k].getAttribute("data-lang") === code) {
                buttons[k].classList.add("active");
            } else {
                buttons[k].classList.remove("active");
            }
        }
        if (typeof global.dispatchEvent === "function") {
            try {
                global.dispatchEvent(new CustomEvent("simust-lang-change", { detail: code }));
            } catch (e) {}
        }
    }

    function fillCountrySelect(selectEl, selected) {
        if (!selectEl) return;
        var current = selected || selectEl.value || "+49";
        selectEl.innerHTML = "";
        for (var i = 0; i < COUNTRY_CODES.length; i++) {
            var opt = document.createElement("option");
            opt.value = COUNTRY_CODES[i].code;
            opt.textContent = COUNTRY_CODES[i].label;
            selectEl.appendChild(opt);
        }
        selectEl.value = current;
        if (!selectEl.value) selectEl.value = "+49";
    }

    function bindLangSwitcher(root) {
        var scope = root || document;
        var buttons = scope.querySelectorAll(".lang-btn[data-lang]");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener("click", function (e) {
                e.preventDefault();
                setLang(this.getAttribute("data-lang"));
            });
        }
        applyI18n(getLang());
    }

    global.SIMUST_I18N = I18N;
    global.SIMUST_COUNTRY_CODES = COUNTRY_CODES;
    global.simustGetLang = getLang;
    global.simustSetLang = setLang;
    global.simustT = t;
    global.simustApplyI18n = applyI18n;
    global.simustFillCountrySelect = fillCountrySelect;
    global.simustBindLangSwitcher = bindLangSwitcher;
})(window);
