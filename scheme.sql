/* MariaDB */
/* This is just a summary of needed table for public use. */
CREATE TABLE volum_vms (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `ctid` INT NOT NULL,
    `internal_ip` VARCHAR(15) NOT NULL
);

CREATE TABLE volum_ssh_logs (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `time_at` DATETIME DEFAULT NOW(),
    `vm_id` INT NOT NULL,
    `username` VARCHAR(20) NOT NULL,
    `command` VARCHAR(10000)
);