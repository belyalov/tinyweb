#!/usr/bin/env micropython
"""
MIT license
(C) Konstantin Belyalov 2017-2018
"""
import tinyweb

# Init our customers DB with some fake values
db = {'1': {'firstname': 'Alex', 'lastname': 'River'},
      '2': {'firstname': 'Lannie', 'lastname': 'Fox'}}
next_id = 3


# If you're familiar with FLaskRestful - you're almost all set! :)
# Tinyweb have only basic functionality comparing to Flask due to
# environment where it intended to run on.
class CustomersList():

    def get(self, data):
        """Return list of all customers"""
        return db

    def post(self, data):
        """Add customer"""
        global next_id
        db[str(next_id)] = data
        next_id += 1
        # Return message AND set HTTP response code to "201 Created"
        return {'message': 'created'}, 201


# Simple helper to return message and error code
def not_found():
    # Return message and HTTP response "404 Not Found"
    return {'message': 'no such customer'}, 404


# Detailed information about given customer
class Customer():

    def not_exists(self):
        return {'message': 'no such customer'}, 404

    def get(self, data, user_id):
        """Get detailed information about given customer"""
        if user_id not in db:
            return not_found()
        return db[user_id]

    def put(self, data, user_id):
        """Update given customer"""
        if user_id not in db:
            return not_found()
        db[user_id] = data
        return {'message': 'updated'}

    def delete(self, data, user_id):
        """Delete customer"""
        if user_id not in db:
            return not_found()
        del db[user_id]
        return {'message': 'successfully deleted'}


def run():
    # Create web server application
    app = tinyweb.webserver()
    # Add our resources
    app.add_resource(CustomersList, '/customers')
    app.add_resource(Customer, '/customers/<user_id>')
    app.run(host='0.0.0.0', port=8081)


if __name__ == '__main__':
    run()
    # To test your server run in terminal:
    # - Get all customers:
    #       curl http://localhost:8081/customers
    # - Get detailed information about particular customer:
    #       curl http://localhost:8081/customers/1
    # - Add customer:
    #       curl http://localhost:8081/customers -X POST -d "firstname=Maggie&lastname=Stone"
    # - Update customer:
    #       curl http://localhost:8081/customers/2 -X PUT -d "firstname=Margo"
    # - Delete customer:
    #       curl http://localhost:8081/customers/1 -X DELETE
