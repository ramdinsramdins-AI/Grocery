// Firebase settings for accounts (account.js). While nothing is pasted below, accounts stay switched off and lists
// save on each device only. To switch them on, follow "Accounts" in README.md: in the Firebase console open
// Project settings, find "Your apps", pick "Config", copy from "const firebaseConfig = {" down to "};" and paste it
// between the two marker lines. These settings are not secret (every visitor's browser needs them to reach Firebase);
// firestore.rules is what keeps each person's list private.

// ---- paste below this line ----

// ---- paste above this line ----

window.SHELFCHECK_FIREBASE = typeof firebaseConfig === "undefined" ? null : firebaseConfig;
