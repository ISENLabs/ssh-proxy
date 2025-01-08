/* MariaDB */
/* This is just a summary of needed table for public use. */
CREATE TABLE volum_vms (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `ctid` INT NOT NULL,
    `internal_ip` VARCHAR(15) NOT NULL
);